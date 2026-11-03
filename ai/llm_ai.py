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

    # ===================== 大模型请求 =====================

    def _ask_llm(self, board, legal: List[Tuple[int, int]],
                 result: dict) -> None:
        """后台线程任务：带重试地请求大模型并解析落子（结果写入 result）。"""
        api_key = load_api_key(self.model)
        if not api_key:
            result["move"] = random.choice(legal)
            self.think.note = "未配置 API Key：已临时随机走子，请到主菜单「大模型设置」配置"
            log_warn("LlmAI 未配置 API Key，已随机兜底")
            return

        max_retries = max(1, int(getattr(self.config, "llm_max_retries", 3)))
        last_hint = ""
        for attempt in range(1, max_retries + 1):
            self.think.note = f"调用大模型（第 {attempt}/{max_retries} 次）…"
            try:
                text = self._chat(api_key, board, legal, last_hint)
            except Exception as exc:  # 网络错误 / 超时 / 响应异常均重试
                log_warn(f"LlmAI 请求失败（{exc}）")
                continue
            move = self._parse_move(text)
            if move in legal:
                result["move"] = move
                log_info(f"LlmAI 落子 ({move[0]},{move[1]})：{self.model}")
                return
            last_hint = f"（你上次回答「{text.strip()[:40]}」不是合法空位，请重新选择）"

        # 重试耗尽：随机兜底，保证对局不中断
        result["move"] = random.choice(legal)
        self.think.note = "大模型响应异常，已随机兜底"
        log_warn("LlmAI 多次重试仍无合法落子，已随机兜底")

    def _chat(self, api_key: str, board, legal: List[Tuple[int, int]],
              last_hint: str) -> str:
        """
        调用 OpenAI 兼容 /v1/chat/completions 接口。

        返回：
            模型回复的文本内容。
        """
        prompt = self._build_prompt(board, legal, last_hint)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是棋类对局引擎，只输出落子坐标。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(getattr(self.config, "llm_temperature", 0.2)),
            "max_tokens": 16,
            "stream": False,
        }
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    # ===================== 局面编码与响应解析 =====================

    def _build_prompt(self, board, legal: List[Tuple[int, int]],
                      last_hint: str) -> str:
        """把当前局面编码为发给大模型的文本指令。"""
        mine, theirs = [], []
        for r in range(board.size):
            for c in range(board.size):
                piece = board.board[r][c]
                if piece == self.player:
                    mine.append((r, c))
                elif piece == board.opponent(self.player):
                    theirs.append((r, c))

        side = "黑方" if self.player == BLACK else "白方"
        game_desc, strategy = self._game_hint(board)
        lines = [
            f"你现在是{game_desc}对局中的{side}。棋盘 {board.size}x{board.size}，"
            "坐标用 (行,列)，从 0 开始。",
            f"你（{side}）的棋子：{mine or '（暂无）'}",
            f"对方棋子：{theirs or '（暂无）'}",
            f"规则与策略：{strategy}",
            f"当前合法空位共 {len(legal)} 个，只能从中选择。",
            "请只输出一个落子坐标，格式严格为两个数字加逗号，例如：7,7。"
            "不要输出任何解释或多余文字。",
        ]
        if last_hint:
            lines.append(last_hint)
        return "\n".join(lines)

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

    # ===================== 界面显示 =====================

    @property
    def label(self) -> str:
        """返回「黑方 大模型」形式的显示标签。"""
        side = "黑方" if self.player == BLACK else "白方"
        return f"{side} {self.display_name}"
