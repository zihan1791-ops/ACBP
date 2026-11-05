# -*- coding: utf-8 -*-
"""
Alpha-Beta 剪枝极大极小（Minimax）搜索 —— 强化版。

相比基础版的四项强化：
1. 候选裁剪：只在已有棋子邻域内搜索，分支因子大幅缩小；
2. 强制预检：己方下一手可成五则直接赢；对手下一手可成五则必须防守；
3. 威胁排序：按「落子后棋型分 + 对手在此落子的防守分」排序走法，
   高价值分支优先搜索、更快触发剪枝；
4. 迭代加深：从第 1 层逐步加深到预算上限，上层最佳走法作为下层首选，
   配合时间上限「超时立即停止」，在有限时间内拿到尽可能深的结论。

另外：思考过程通过 ThinkState + on_progress 回调实时推送到界面。
"""

import math
from typing import Optional, Tuple

from .base_ai import BaseAI
from .evaluator import evaluate
from .candidates import (
    candidate_moves, gomoku_winning_moves, gomoku_attack_points,
    gomoku_defense_points, gomoku_forced_move, sort_moves_by_heuristic,
)
from utils.helpers import MoveTimer
from utils.logger import log_debug

# 终局极端分值（远大于任何中盘启发式评分）
_WIN_SCORE = 1_000_000
_LOSE_SCORE = -1_000_000


class AlphaBetaAI(BaseAI):
    """Alpha-Beta 剪枝 AI（迭代加深 + 威胁排序 + 强制预检）。"""

    name = "alphabeta"
    display_name = "Alpha-Beta"

    def __init__(self, player: int, config) -> None:
        super().__init__(player, config)
        # 迭代加深的最大深度与每步时间上限，来自配置
        self.max_depth = max(1, int(config.ab_depth))
        self.time_limit = float(config.ab_time)
        # 本轮已评估的搜索节点数（用于可视化与日志）
        self._nodes = 0

    # -------------------- 对外接口 --------------------

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        """在候选步中选出 Alpha-Beta 迭代加深评估最优的一步。"""
        legal = candidate_moves(board)
        if not legal:
            return None

        self._begin_think()
        self.think.total = self.max_depth
        self.think.max_depth = self.max_depth
        self._nodes = 0

        # ---- 1. 强制预检：能赢先赢，该挡必挡 ----
        quick_move = self._forced_move(board)
        if quick_move is not None:
            self.think.best_move = quick_move
            self.think.done = 1
            self.think.phase = "强制预检"
            self._emit(on_progress)
            self.think.finish()
            return quick_move

        # ---- 2. 迭代加深搜索 ----
        ordered = sort_moves_by_heuristic(board, legal, self.player)
        # 五子棋：对手活三 / 冲三防守点前置，优先搜索防守分支
        if type(board).__name__ == "GomokuBoard":
            defs = gomoku_defense_points(board, self.player)
            if defs:
                ordered = ([m for m in defs if m in ordered]
                           + [m for m in ordered if m not in defs])
        best_move = ordered[0]
        best_score = -math.inf
        timer = MoveTimer(self.time_limit)
        timer.start()

        for depth in range(1, self.max_depth + 1):
            if timer.timeout:
                break  # 时间用完，停止加深，使用已有结论

            alpha, beta = -math.inf, math.inf
            layer_best_move, layer_best_score = ordered[0], -math.inf

            for move in ordered:
                child = board.copy()
                child.apply_move(move)
                score = self._search(child, depth - 1, alpha, beta)
                if score > layer_best_score:
                    layer_best_score, layer_best_move = score, move
                if score > alpha:
                    alpha = score
                if timer.timeout:
                    break  # 单层内部也检查超时

            # 该层结论成为新的最优，且作为下一层的首选走法
            best_move, best_score = layer_best_move, layer_best_score
            ordered = [m for m in ordered if m != layer_best_move] or ordered
            ordered = [layer_best_move] + ordered

            # 更新思考状态并推送可视化
            self.think.depth = depth
            self.think.done = self._nodes
            self.think.best_move = best_move
            self.think.best_value = best_score
            self.think.elapsed = timer.elapsed()
            self.think.phase = f"迭代加深 · 第 {depth} 层"
            self._emit(on_progress)

        log_debug(f"{self.label} 深度 {self.think.depth}，节点 {self._nodes}，"
                  f"选定 {best_move}，评分 {best_score:.1f}")
        self.think.finish()
        return best_move

    # -------------------- 强制预检 --------------------

    def _forced_move(self, board) -> Optional[Tuple[int, int]]:
        """
        五子棋四层战术预检，统一复用 ai.candidates.gomoku_forced_move。
        第四层额外覆盖跳三 1101 / 1011 补中间成活四的强制堵点。
        """
        result = gomoku_forced_move(board, self.player)
        if result is not None:
            move, note = result
            self.think.note = note
            return move
        return None

    # -------------------- 搜索核心 --------------------

    def _search(self, board, depth: int, alpha: float, beta: float) -> float:
        """
        递归极大极小搜索。返回值始终以 self.player（本 AI 一方）视角表示。
        """
        self._nodes += 1

        # 终局：直接返回极端分值
        if board.game_over:
            return self._terminal_score(board)

        # 达到深度上限：启发式评估当前局面
        if depth == 0:
            return evaluate(board, self.player)

        legal = candidate_moves(board)
        if not legal:
            # 当前方无合法步（如黑白棋被迫停手），直接评估局面交回上层判断
            return evaluate(board, self.player)

        ordered = sort_moves_by_heuristic(board, legal, board.current_player)

        if board.current_player == self.player:
            # 极大层：轮到己方，追求最高分
            best = -math.inf
            for move in ordered:
                child = board.copy()
                child.apply_move(move)
                score = self._search(child, depth - 1, alpha, beta)
                best = max(best, score)
                alpha = max(alpha, best)
                if beta <= alpha:      # 剪枝：后续分支不可能更优
                    break
            return best
        else:
            # 极小层：轮到对手，假设对手选择对己方最不利的走法
            best = math.inf
            for move in ordered:
                child = board.copy()
                child.apply_move(move)
                score = self._search(child, depth - 1, alpha, beta)
                best = min(best, score)
                beta = min(beta, best)
                if beta <= alpha:      # 剪枝：后续分支不可能更差
                    break
            return best

    def _terminal_score(self, board) -> float:
        """终局局面打分：己方大胜、己方大败、平局分别给极端 / 中性分值。"""
        opponent = board.opponent(self.player)
        if board.winner == self.player:
            return _WIN_SCORE
        if board.winner == opponent:
            return _LOSE_SCORE
        return 0.0  # 平局
