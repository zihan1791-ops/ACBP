# -*- coding: utf-8 -*-
"""
大模型棋手（LlmAI）。

实现思路：
1. 把当前棋盘局面编码为文本（己方 / 对方棋子坐标 + 规则与策略提示），
   通过「OpenAI 兼容格式」的 /v1/chat/completions 接口发给大模型；
2. 解析模型返回的落子坐标并校验合法性，非法或调用失败自动重试；
3. 网络请求放在后台线程执行，主线程轮询线程状态并持续推送思考进度
   （on_progress），保证 AI 等待大模型响应期间界面不冻结、可实时看到
   「等待大模型响应 N 秒」的进度提示；
4. 未配置 API Key 或重试仍失败时，退化为随机合法步兜底并给出明确提示，
   保证对局流程永不卡死。

接入任何 OpenAI 兼容的大模型服务商只需改 settings.py 中的
LLM_BASE_URL / LLM_MODEL（如 DeepSeek、通义、豆包、智谱等）。
"""

import json
import random
import re
import threading
import time
import urllib.request
import urllib.error

from typing import List, Optional, Tuple

from core.base_board import BLACK
from config.llm_keys import load_api_key
from utils.logger import log_info, log_warn
from .base_ai import BaseAI

# 单次请求的最大输出 token 默认值（可被 config/settings.py 的 LLM_MAX_TOKENS 覆盖）。
# DeepSeek 对该参数的合法范围是 [1, 393216]，越界会直接返回 400
# invalid_request_error（「Invalid max_tokens value」）；棋类每步只需回一个
# 落子坐标，8192 足够容纳 deepseek-flash 的思考内容，且远低于上限。
_MAX_TOKENS = 8192

# 「数字,数字」形式的坐标候选（兼容中文逗号与空格分隔）
_MOVE_PAIR_RE = re.compile(r"(\d{1,2})\s*[,，]\s*(\d{1,2})")


class LlmAI(BaseAI):
    """通过大模型 API 选择走子的人工智能棋手。"""

    # 算法标识（棋谱 / 工厂注册用）；display_name 用于界面与日志显示
    name = "llm"
    display_name = "大模型"

    def __init__(self, player: int, config) -> None:
        super().__init__(player, config)
        self.model = getattr(config, "llm_model", "deepseek-flash")
        self.base_url = getattr(config, "llm_base_url", "https://api.deepseek.com")

    # ===================== 主入口 =====================

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        """在当前局面选择一步落子：编码局面 → 调大模型 → 解析校验。"""
        legal = board.get_legal_moves()
        if not legal:
            return None

        self._begin_think()
        self.think.phase = "调用大模型"
        self.think.total = 0

        # 网络请求放后台线程，主线程轮询并推送进度，界面不冻结
        result: dict = {}
        worker = threading.Thread(
            target=self._ask_llm, args=(board, legal, result),
            daemon=True)
        worker.start()

        start = time.time()
        while worker.is_alive():
            worker.join(0.1)
            self.think.elapsed = time.time() - start
            if not self.think.note:
                self.think.note = "等待大模型响应…"
            self._emit(on_progress)

        self.think.finish()
        self._emit(on_progress)
        return result.get("move")

    def propose(self, board, k: int = 3, on_progress=None
                ) -> List[Tuple[int, int]]:
        """
        只做「提名」，不直接落子：请大模型给出至多 k 个候选点。

        供「大模型提名 + MCTS 验证」模式（见 ai.llm_assisted）使用：大模型
        负责从战术要点里挑出值得深算的少数分支，MCTS 再在这些分支内做完整
        搜索，既保留模型的棋理判断，又用真实模拟胜负兜住它的误判。

        返回的列表按模型给出的优先级排序，首个即模型首选；模型调用失败或
        候选不足 k 个时，用启发式候选补齐，保证搜索层始终有足够分支。
        """
        legal = board.get_legal_moves()
        if not legal:
            return []
        k = max(1, min(int(k), len(legal)))
        if k == 1:
            move = self.select_move(board, on_progress)
            return [move] if move is not None else []

        self._begin_think()
        self.think.phase = f"大模型提名 {k} 个候选"
        self.think.total = 0

        result: dict = {}
        worker = threading.Thread(
            target=self._ask_llm, args=(board, legal, result, k), daemon=True)
        worker.start()

        start = time.time()
        while worker.is_alive():
            worker.join(0.1)
            self.think.elapsed = time.time() - start
            if not self.think.note:
                self.think.note = "等待大模型提名…"
            self._emit(on_progress)

        self.think.finish()
        self._emit(on_progress)

        moves = [m for m in result.get("moves", []) if m in legal]
        if len(moves) < k:
            for m in self._heuristic_fill(board, legal, k):
                if m not in moves:
                    moves.append(m)
                if len(moves) >= k:
                    break
        # 棋种硬优先点插到最前：黑白棋抢角、五子棋成五/堵五这类「不靠模型
        # 判断也必须进搜索」的点，一旦漏在提名外，限制后的 MCTS 就搜不到。
        merged: List[Tuple[int, int]] = []
        for m in self._priority_candidates(board, legal) + moves + legal:
            if m in legal and m not in merged:
                merged.append(m)
            if len(merged) >= k:
                break
        return merged

    def _priority_candidates(self, board, legal: List[Tuple[int, int]]
                             ) -> List[Tuple[int, int]]:
        """
        与棋种相关的硬优先候选（不依赖模型判断）：

        - 黑白棋：可占的角位——角不会被翻转，是全局最高价值点；
        - 五子棋：成五点与堵五点——MCTS 强制预检虽已覆盖，但进提名后
          搜索层能围绕它展开，胜率统计更完整；
        - 其它棋种：无。
        """
        kind = type(board).__name__
        if kind == "OthelloBoard":
            size = board.size
            corners = [(0, 0), (0, size - 1), (size - 1, 0), (size - 1, size - 1)]
            return [m for m in corners if m in legal]
        if kind == "GomokuBoard":
            pts = self._tactical_points(board)
            out: List[Tuple[int, int]] = []
            for key in ("win", "block"):
                for m in pts.get(key, []):
                    if m in legal and m not in out:
                        out.append(m)
            return out
        return []

    def _heuristic_fill(self, board, legal: List[Tuple[int, int]],
                        k: int) -> List[Tuple[int, int]]:
        """启发式候选补齐：邻域裁剪 + 棋理分排序，作为模型提名不足时的兜底。"""
        try:
            from ai.candidates import candidate_moves, sort_moves_by_heuristic
            cand = [m for m in candidate_moves(board) if m in legal]
            ranked = sort_moves_by_heuristic(board, cand, self.player)
        except Exception:  # 未知棋种或缺接口：退回原始合法步顺序
            ranked = []
        out = [m for m in ranked if m in legal]
        out.extend(m for m in legal if m not in out)
        return out[:k]

    # ===================== 大模型请求 =====================

    def _ask_llm(self, board, legal: List[Tuple[int, int]],
                 result: dict, want: int = 1) -> None:
        """
        后台线程任务：带重试地请求大模型并解析落子（结果写入 result）。

        want == 1 时 result 写入单个 move；want > 1 时额外写入 moves 列表
        （模型提名的候选，按优先级排序），两者都写 move = 首个候选。
        """
        api_key = load_api_key(self.model)
        if not api_key:
            result["move"] = random.choice(legal)
            result["moves"] = [result["move"]]
            self.think.note = "未配置 API Key：已临时随机走子，请到主菜单「大模型设置」配置"
            log_warn("LlmAI 未配置 API Key，已随机兜底")
            return

        max_retries = max(1, int(getattr(self.config, "llm_max_retries", 3)))
        last_hint = ""
        for attempt in range(1, max_retries + 1):
            self.think.note = f"调用大模型（第 {attempt}/{max_retries} 次）…"
            try:
                reply = self._chat(api_key, board, legal, last_hint, want)
            except Exception as exc:  # 网络错误 / 超时 / 响应异常均重试
                log_warn(f"LlmAI 请求失败（{exc}）")
                continue
            moves = self._resolve_moves(reply, legal, want)
            if moves:
                result["moves"] = moves
                result["move"] = moves[0]
                log_info(f"LlmAI 落子 ({moves[0][0]},{moves[0][1]})：{self.model}")
                if want > 1:
                    log_info(f"LlmAI 提名候选：{moves}")
                return
            shown = (reply["content"] or reply["reasoning"]).strip()[:40]
            if want > 1:
                last_hint = (f"（你上次只给出「{shown or '空'}」，不足 {want} 个合法候选；"
                             "请按「行,列;行,列;行,列」格式重新给出）")
            else:
                last_hint = f"（你上次回答「{shown or '空'}」不是合法空位，请重新选择）"
            if reply["finish_reason"] == "length":
                log_warn("LlmAI 输出被 max_tokens 截断（finish_reason=length），"
                         "可调大 LLM_MAX_TOKENS")

        # 重试耗尽：随机兜底，保证对局不中断
        result["move"] = random.choice(legal)
        result["moves"] = [result["move"]]
        self.think.note = "大模型响应异常，已随机兜底"
        log_warn("LlmAI 多次重试仍无合法落子，已随机兜底")

    def _chat(self, api_key: str, board, legal: List[Tuple[int, int]],
              last_hint: str, want: int = 1) -> dict:
        """
        调用 OpenAI 兼容 /v1/chat/completions 接口。

        返回：
            {"content": 正式回复, "reasoning": 思考内容, "finish_reason": 结束原因}。
            思考型模型（deepseek-flash）偶发返回空 content、答案只留在
            reasoning_content 里，因此两者都带回给上层解析。
        """
        prompt = self._build_prompt(board, legal, last_hint, want)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是棋类对局引擎，只输出落子坐标。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(getattr(self.config, "llm_temperature", 0.2)),
            "max_tokens": int(getattr(self.config, "llm_max_tokens", _MAX_TOKENS)),
            "stream": False,
        }
        # 默认关闭「先思考」：棋类每步只需要一个坐标，让思考型模型先写几千字
        # 推理，既把 max_tokens 吃满（content 被截断为空、finish_reason=length），
        # 又把单步耗时推到 20~40 秒。关掉后约 1 秒返回，坐标直接落在 content 里。
        if not getattr(self.config, "llm_enable_thinking", False):
            payload["thinking"] = {"type": "disabled"}
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        timeout = float(getattr(self.config, "llm_timeout", 60.0))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 4xx 的原因写在响应体里（max_tokens 越界 / 模型名不存在 / Key 无效等），
            # 只打印 str(exc) 会退化成「HTTP Error 400: Bad Request」，无法定位，
            # 这里把服务端错误体一并带进日志后再抛出，交由上层重试 / 兜底。
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                detail = ""
            log_warn(f"LlmAI 请求被拒绝：HTTP {exc.code} {detail[:500]}")
            raise
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return {
            "content": message.get("content") or "",
            "reasoning": message.get("reasoning_content") or "",
            "finish_reason": choice.get("finish_reason") or "",
        }

    # ===================== 局面编码与响应解析 =====================

    def _build_prompt(self, board, legal: List[Tuple[int, int]],
                      last_hint: str, want: int = 1) -> str:
        """
        把当前局面编码为发给大模型的文本指令。

        除棋子坐标外，还直接给出三样模型自己算不出来的东西：
        1. 文本棋盘——模型对二维网格的空间理解远好于元组列表；
        2. 战术要点——成五 / 堵五 / 活四 / 堵活三，由候选层算好后翻译成句子；
        3. 优先落子清单——战术点在前，邻域候选在后，缩小选择面。

        want > 1 时要求输出多个候选（供「大模型提名 + MCTS 验证」模式使用）。
        """
        side = "黑方" if self.player == BLACK else "白方"
        game_desc, strategy = self._game_hint(board)
        opp = board.opponent(self.player)
        mine = theirs = 0
        for r in range(board.size):
            for c in range(board.size):
                piece = board.board[r][c]
                if piece == self.player:
                    mine += 1
                elif piece == opp:
                    theirs += 1

        pts = self._tactical_points(board)
        lines = [
            f"你现在是{game_desc}对局中的{side}。棋盘 {board.size}x{board.size}，"
            "坐标用 (行,列)，从 0 开始。● 是你的棋子，○ 是对手的，· 是空位：",
            self._render_board(board),
            f"你（{side}）已有 {mine} 子，对方 {theirs} 子。",
            f"规则与策略：{strategy}",
        ]
        lines.extend(self._threat_lines(pts))
        if type(board).__name__ == "OthelloBoard":
            lines.extend(self._othello_lines(board, legal))
        lines.append(f"当前合法空位共 {len(legal)} 个：{self._legal_hint(board, legal, pts)}")

        if want > 1:
            lines.append(f"请按优先级给出 {want} 个候选落子坐标，用分号分隔，"
                         "例如：7,7;8,8;6,6。只输出坐标，不要解释。")
        else:
            lines.append("只能从上述位置中选择。请只输出一个落子坐标，"
                         "格式严格为两个数字加逗号，例如：7,7。不要输出任何解释或多余文字。")
        if last_hint:
            lines.append(last_hint)
        return "\n".join(lines)

    def _tactical_points(self, board) -> dict:
        """五子棋战术点（成五 / 堵五 / 活四 / 堵活三）；其它棋种返回空字典。"""
        if type(board).__name__ != "GomokuBoard":
            return {}
        from ai.candidates import (gomoku_winning_moves, gomoku_attack_points,
                                   gomoku_defense_points)
        opp = board.opponent(self.player)
        return {
            "win": gomoku_winning_moves(board, self.player),
            "block": gomoku_winning_moves(board, opp),
            "attack": gomoku_attack_points(board, self.player),
            "defend": gomoku_defense_points(board, self.player),
        }

    @staticmethod
    def _threat_lines(pts: dict) -> List[str]:
        """把战术点翻译成模型能直接执行的句子（否则它只能自己数棋型）。"""
        if not pts:
            return []
        out = []
        if pts["win"]:
            out.append(f"★ 你下一手落 {pts['win'][:3]} 可直接连成五子取胜，必须走这里。")
        if pts["block"]:
            out.append(f"‼ 对手下一手落 {pts['block'][:3]} 能成五，你必须先堵住其中一处。")
        if pts["attack"]:
            out.append(f"你在 {pts['attack'][:3]} 可形成活四（两端皆空），下一步必胜威胁。")
        if pts["defend"]:
            out.append(f"对手有活三/跳三，端点 {pts['defend'][:4]} 必须堵一个，"
                       "否则对手下一步成活四。")
        return out

    def _othello_lines(self, board, legal: List[Tuple[int, int]]) -> List[str]:
        """黑白棋提示：各步翻子数、可占角、对手可占角。"""
        opp = board.opponent(self.player)
        size = board.size
        corners = [(0, 0), (0, size - 1), (size - 1, 0), (size - 1, size - 1)]
        out = []

        flips = {m: len(board._flip_cells(m[0], m[1], self.player)) for m in legal}
        top = sorted(flips.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
        if top:
            out.append("各合法步可翻转子数（越多越主动）："
                       + "、".join(f"({r},{c})→{n}" for (r, c), n in top))

        my_corners = [m for m in corners if m in legal]
        if my_corners:
            out.append(f"角位 {my_corners} 是你的合法步；角不会被翻转，优先占。")

        opp_corners = [m for m in corners
                       if board.board[m[0]][m[1]] == 0
                       and board._flip_cells(m[0], m[1], opp)]
        if opp_corners:
            out.append(f"⚠ 对手能落角 {opp_corners}，务必抢先占角或切断。")
        return out

    def _render_board(self, board) -> str:
        """把棋盘渲染成等宽文本网格（列号 + 行号，● 己方 / ○ 对手 / · 空位）。"""
        size = board.size
        symbols = {0: "·", self.player: "●", board.opponent(self.player): "○"}
        head = "    " + " ".join(f"{c:2d}" for c in range(size))
        rows = [head]
        for r in range(size):
            cells = " ".join(f" {symbols[board.board[r][c]]}" for c in range(size))
            rows.append(f"{r:2d} " + cells)
        return "\n".join(rows)

    @staticmethod
    def _game_hint(board) -> Tuple[str, str]:
        """按棋种返回中文规则与策略提示（prompt 用）。"""
        cls = board.__class__.__name__.lower()
        if "othello" in cls:
            return ("黑白棋", "落子必须能翻转对手棋子；优先占角、占边、控制中心，"
                             "尽量少给对方翻盘机会。")
        return ("五子棋", "目标连成五子；优先自己连五、活四，同时务必防守对方的"
                         "活三、冲四与跳三。")

    @staticmethod
    def _parse_move(text: str) -> Optional[Tuple[int, int]]:
        """
        从模型回复中解析 (row, col)。

        容错支持的格式：7,7 / (7,7) / [7,7] / 7，7 / “7,7” 等；
        解析不到两个整数时返回 None。
        """
        if not text:
            return None
        nums = re.findall(r"\d{1,2}", text)
        if len(nums) < 2:
            return None
        return (int(nums[0]), int(nums[1]))

    @staticmethod
    def _move_pairs(text: str) -> List[Tuple[int, int]]:
        """提取文本中所有「数字,数字」形式的坐标候选（保持出现顺序）。"""
        if not text:
            return []
        return [(int(a), int(b)) for a, b in _MOVE_PAIR_RE.findall(text)]

    def _resolve_move(self, reply: dict,
                      legal: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """
        从模型返回中解析出合法落子。

        顺序：
        1. content 按原规则整段解析（正常情况 content 只有「7,7」）；
        2. content 内所有「数字,数字」候选，从后往前挑合法者；
        3. reasoning_content 内的候选，从后往前挑合法者——deepseek-flash
           偶发返回空 content，答案仍留在思考内容末尾，这一步把它救回来。

        只有命中 legal 的坐标才会返回，避免把解释文字里的数字误当落子。
        """
        content = reply.get("content") or ""
        reasoning = reply.get("reasoning") or ""

        move = self._parse_move(content)
        if move in legal:
            return move

        for move in reversed(self._move_pairs(content)):
            if move in legal:
                return move
        for move in reversed(self._move_pairs(reasoning)):
            if move in legal:
                return move
        return None

    def _resolve_moves(self, reply: dict, legal: List[Tuple[int, int]],
                       k: int) -> List[Tuple[int, int]]:
        """
        从模型返回中提取至多 k 个合法候选（保持模型给出的先后顺序）。

        与 _resolve_move 的区别：那个只找一个落子、优先取整段解析结果；
        这里要保留模型对多个候选的排序（「A;B;C」中 A 为首选），因此按
        出现顺序收集全部合法坐标并去重。content 不足时再从 reasoning 补。
        """
        if k <= 1:
            move = self._resolve_move(reply, legal)
            return [move] if move is not None else []

        legal_set = set(legal)
        out: List[Tuple[int, int]] = []
        for text in (reply.get("content") or "", reply.get("reasoning") or ""):
            for move in self._move_pairs(text):
                if move in legal_set and move not in out:
                    out.append(move)
                    if len(out) >= k:
                        return out
        return out

    def _legal_hint(self, board, legal: List[Tuple[int, int]],
                    pts: Optional[dict] = None) -> str:
        """
        把合法落子整理成 prompt 里的坐标清单。

        优先级：战术要点（成五 / 堵五 / 活四 / 堵活三）→ 邻域启发式候选。
        空位很少时全量列出；否则最多列 24 个，其余只报数量——校验仍按全量
        legal 执行，模型选中清单外的合法点也不会被判非法。
        """
        if pts is None:
            pts = self._tactical_points(board)

        picks: List[Tuple[int, int]] = []
        seen = set()
        for key in ("win", "block", "attack", "defend"):
            for m in pts.get(key, []):
                if m in legal and m not in seen:
                    seen.add(m)
                    picks.append(m)

        if len(legal) <= 24:
            picks, suffix = list(legal), ""
        elif picks:
            picks = picks[:24]
            suffix = (f"（其余 {len(legal) - len(picks)} 个空位也可落子，"
                      "以上为战术要点与优先候选）")
        else:
            from ai.candidates import candidate_moves, sort_moves_by_heuristic
            cand = [m for m in candidate_moves(board) if m in legal]
            picks = sort_moves_by_heuristic(board, cand, self.player)[:24] or legal[:24]
            suffix = f"（其余 {len(legal) - len(picks)} 个空位也可落子，以上为优先候选）"
        return "、".join(f"({r},{c})" for r, c in picks) + suffix

    # ===================== 界面显示 =====================

    @property
    def label(self) -> str:
        """返回「黑方 大模型」形式的显示标签。"""
        side = "黑方" if self.player == BLACK else "白方"
        return f"{side} {self.display_name}"
