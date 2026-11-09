# -*- coding: utf-8 -*-
"""
对局控制器（GameController）。

职责：
1. 维护棋盘与双方玩家，按规则层给出的 current_player 调度回合；
2. 人类回合接收界面点击落子；AI 回合调用对应算法选步落子；
3. 落子后刷新胜负状态、生成界面提示文本；
4. 提供悔棋（快照回退）、重开、围棋手动结束对局等操作。

控制器不直接绘制界面，也不实现规则；规则全部来自 core 棋盘类，算法来自 ai 包。
"""

from typing import Optional, Tuple
import json
import os
from datetime import datetime

from core.base_board import BaseBoard, BLACK, WHITE, DRAW, EMPTY
from .player import Player
from utils.logger import log_info
from utils.paths import resolve_path


class GameController:
    """一局对局的状态机与调度器。"""

    def __init__(self, board: BaseBoard, player1: Player, player2: Player,
                 config, game_kind: str, board_size: int) -> None:
        self.board = board
        # 玩家字典：键为玩家编号（BLACK / WHITE）
        self.players = {BLACK: player1, WHITE: player2}
        # 双方棋子外观：供棋盘视图与棋谱保存共用
        self.skins = {BLACK: player1.skin, WHITE: player2.skin}
        self.config = config
        self.game_kind = game_kind
        self.board_size = board_size

        # 落子前棋盘快照栈：悔棋时逐级回退
        self._snapshots = []
        # 开局初始局面副本：重开时直接复原，无需重新调用棋盘工厂
        self._initial_state = board.copy()

        # 界面状态标记：AI 是否正在思考、最近一条提示消息
        self.ai_thinking = False
        self.last_event = ""

        # ---- 棋谱记录 ----
        # 每步记录：{"player": 落子方编号, "move": [row, col]}
        self.moves: list = []
        self.started_at = datetime.now()

    # ===================== 回合查询 =====================

    @property
    def current_player(self) -> Player:
        """当前回合对应的玩家对象。"""
        return self.players[self.board.current_player]

    @property
    def current_is_ai(self) -> bool:
        """当前回合是否由 AI 行动。"""
        return not self.current_player.is_human

    @property
    def is_over(self) -> bool:
        """对局是否已经结束。"""
        return self.board.game_over

    # ===================== 落子入口 =====================

    def handle_human_move(self, move: Tuple[int, int]) -> bool:
        """
        人类玩家点击棋盘后的落子入口。

        返回：
            True 落子成功；False 表示当前不是人类回合 / 位置非法 / 对局已结束。
        """
        if self.board.game_over:
            return False
        if not self.current_player.is_human:
            return False

        legal = self.board.get_legal_moves()
        if move not in legal:
            reason = ""
            if hasattr(self.board, "repeat_block_reason"):
                reason = self.board.repeat_block_reason(move)
            self.last_event = reason or "该位置不合法，请重新选择"
            return False

        self._push_snapshot()
        self.board.apply_move(move)
        self._after_move()
        return True

    def step_ai(self, on_progress=None) -> Optional[Tuple[int, int]]:
        """
        AI 回合推进一步：调用 AI 算法选步并落子。

        参数：
            on_progress: 可选回调，透传给 AI 的思考过程（界面实时可视化用）。
        返回实际落子坐标；当前不是 AI 回合或无合法步时返回 None。
        """
        if self.board.game_over:
            return None
        player = self.current_player
        if player.is_human:
            return None

        self.ai_thinking = True
        move = player.ai.select_move(self.board, on_progress=on_progress)
        self.ai_thinking = False
        return self.apply_ai_move(move, player)

    def apply_ai_move(self, move: Optional[Tuple[int, int]],
                      player: Optional[Player] = None,
                      validate: bool = False) -> Optional[Tuple[int, int]]:
        """
        应用一步已经算好的 AI 走子：同步 step_ai 与多进程调度层共用，
        保证快照、棋谱、终局保存等收尾逻辑只有一份。

        参数：
            move:     AI 选出的坐标；
            player:   落子方（省略则取当前回合方）；
            validate: 多进程路径置 True——局面可能在计算期间被悔棋 / 重开改变，
                      此时丢弃过期走子，避免把旧局面的棋下到新棋盘上。
        """
        if self.board.game_over:
            return None
        player = player or self.current_player
        if player.is_human:
            return None
        if move is None:
            self.last_event = f"{player.describe()} 无合法步可走"
            return None
        if validate:
            legal = self.board.get_legal_moves()
            if legal and move not in legal:
                self.last_event = "局面已变化，AI 走子已丢弃"
                return None

        self._push_snapshot()
        self.board.apply_move(move)
        self._after_move()
        return move

    def _after_move(self) -> None:
        """落子后的统一收尾：棋谱记录、日志与终局提示生成。"""
        # 记录棋谱：落子方 = 刚落下棋子的颜色（apply_move 后仍可读取）
        last = self.board.last_move
        if last is not None:
            # 象棋棋子编码为 side*10+kind，由棋盘自己给出落子方
            side = (self.board.last_player() if hasattr(self.board, "last_player")
                    else self.board.board[last[0]][last[1]])
            self.moves.append({
                "player": side,
                "move": [last[0], last[1]],
            })
        log_info(f"已落子 {self.board.move_count} 手，当前轮到 "
                 f"{self.current_player.describe()}")
        if self.board.game_over:
            self.last_event = self.result_text()
            log_info(self.last_event)
            self._save_record()

    # ===================== 对局操作 =====================

    def undo(self, steps: int = 1) -> bool:
        """
        悔棋：回退最近 steps 步到上一个快照。

        人机大战建议一次回退 2 步（人类一步 + AI 一步），由调用方传入步数。
        """
        restored = 0
        for _ in range(steps):
            if not self._snapshots:
                break
            self.board = self._snapshots.pop()
            if self.moves:
                self.moves.pop()  # 棋谱同步回退
            restored += 1
        if restored:
            self.last_event = f"已悔棋 {restored} 步"
        return restored > 0

    def restart(self) -> None:
        """清空快照并复原到开局局面。"""
        self.board = self._initial_state.copy()
        self._snapshots.clear()
        self.moves.clear()
        self.started_at = datetime.now()
        self.last_event = "对局已重新开始"

    def finish_manually(self) -> None:
        """
        手动结束对局（围棋专用）：触发规则层简化数子并写入胜负。
        其它棋种规则层会自动判定终局，无需调用本方法。
        """
        if hasattr(self.board, "end_game_manually"):
            self.board.end_game_manually()
            self.last_event = self.result_text()
            self._save_record()

    # ===================== 界面展示文本 =====================

    def result_text(self) -> str:
        """生成终局结果中文描述。"""
        if self.board.winner == DRAW:
            return "对局结束：双方平局"
        if self.board.winner == EMPTY:
            return "对局结束"
        return f"对局结束：{self.players[self.board.winner].describe()} 获胜！"

    def status_text(self) -> str:
        """生成当前回合 / 终局提示文本，供界面状态栏显示。"""
        if self.board.game_over:
            return self.result_text()
        return f"轮到 {self.current_player.describe()} 落子"

    def score_line(self) -> str:
        """
        纯比分文本（双方子数 / 提子），供对局栏与结算遮罩共用。

        象棋按将死判胜，不以子数计分，故返回空串。
        """
        if not hasattr(self.board, "count_pieces") \
                or hasattr(self.board, "repeat_status"):
            return ""
        black, white = self.board.count_pieces()
        text = f"黑方 {black} 子 : 白方 {white} 子"
        # 围棋额外显示提子数
        if hasattr(self.board, "black_captured"):
            text += (f" ｜ 黑提白 {self.board.black_captured}"
                     f" ｜ 白提黑 {self.board.white_captured}")
        return text

    def score_text(self) -> str:
        """
        生成对局栏的统计文本；不支持统计的棋种返回空串。

        象棋的「长打须变着」是规则，不占版面：只在违规被拒时给一次临时
        事件提示，此处不常驻显示重复计数。
        """
        return self.score_line()

    # ===================== 内部工具 =====================

    def _push_snapshot(self) -> None:
        """落子前保存棋盘快照，供悔棋回退。"""
        self._snapshots.append(self.board.copy())

    # ===================== 棋谱保存 =====================

    def _player_role(self, player: Player) -> dict:
        """把玩家对象序列化为棋谱中的角色信息（含棋子外观）。"""
        if player.is_human:
            return {"type": "human", "skin": player.skin}
        return {"type": "ai", "ai": player.ai.name, "skin": player.skin}

    def _mode_label(self) -> str:
        """根据双方身份推断对局模式（人机大战 / 算法 PK / 人人对战）。"""
        p1, p2 = self.players[BLACK], self.players[WHITE]
        if not p1.is_human and not p2.is_human:
            return "ai_vs_ai"
        if p1.is_human and p2.is_human:
            return "human_vs_human"
        return "human_vs_ai"

    def _save_record(self) -> None:
        """终局后把本局棋谱（含双方角色、全部落子、胜负）写入 JSON 文件。

        棋谱按「开局日期」分文件夹永久保存：records/YYYY-MM-DD/…
        同名棋谱自动追加序号，绝不覆盖既有文件。
        """
        if not getattr(self.config, "save_records", False):
            return

        record_root = resolve_path(getattr(self.config, "records_dir", "records"))
        # 按开局日期分子文件夹，实现永久保存与按天归档
        day_dir = os.path.join(record_root, self.started_at.strftime("%Y-%m-%d"))
        try:
            os.makedirs(day_dir, exist_ok=True)
        except OSError as exc:
            log_info(f"棋谱目录创建失败：{exc}")
            return

        winner = self.board.winner
        record = {
            "game": self.game_kind,
            "board_size": self.board_size,
            "mode": self._mode_label(),
            "first_player": self.config.first_player,
            "players": {
                "black": self._player_role(self.players[BLACK]),
                "white": self._player_role(self.players[WHITE]),
            },
            "moves": self.moves,
            "winner": winner if winner is not None else None,
            "result_text": self.result_text(),
            "ai_budget": {
                "mcts_iterations": self.config.mcts_iterations,
                "mcts_time": self.config.mcts_time,
                "ab_depth": self.config.ab_depth,
                "ab_time": self.config.ab_time,
                "evo_population": self.config.get("evo_population", 30),
                "evo_generations": self.config.get("evo_generations", 50),
                "evo_horizon": self.config.get("evo_horizon", 6),
                "evo_time": self.config.get("evo_time", 8.0),
            },
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": datetime.now().isoformat(timespec="seconds"),
        }

        fname = f"{self.game_kind}_{self.started_at.strftime('%Y%m%d_%H%M%S')}.json"
        fpath = os.path.join(day_dir, fname)
        # 同名文件（如续局）追加序号，避免覆盖既有棋谱
        seq = 2
        while os.path.exists(fpath):
            stem = fname[:-5]
            fpath = os.path.join(day_dir, f"{stem}_{seq}.json")
            seq += 1
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            log_info(f"棋谱已保存：{fpath}")
        except OSError as exc:
            log_info(f"棋谱保存失败：{exc}")
