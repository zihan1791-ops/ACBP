# -*- coding: utf-8 -*-
"""
Edax 黑白棋专用 AI：对外仍是 BaseAI.select_move(board, on_progress)，
内部把局面转成 OBF 交给外部引擎，再把主变例首着作为落子返回。

仅在 OthelloBoard 上生效；五子棋等其它棋种直接委托现有 Alpha-Beta，
外部引擎永远不会在五子棋里被调用。引擎缺失 / 超时 / 输出异常时
退化为启发式最佳合法步，保证对局不中断。
"""

import time
from typing import Optional, Tuple

from ai.base_ai import BaseAI
from ai.candidates import sort_moves_by_heuristic
from . import is_available, level, time_limit
from .protocol import solve


class EdaxAI(BaseAI):
    """黑白棋专用：Edax 4.6 外部引擎适配器。"""

    name = "edax"
    display_name = "Edax"

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        if type(board).__name__ != "OthelloBoard":
            from ai.alpha_beta import AlphaBetaAI
            return AlphaBetaAI(self.player, self.config).select_move(
                board, on_progress)

        self._begin_think()
        legal = board.get_legal_moves()
        if not legal:
            self.think.note = "无合法步，停一手"
            self.think.finish()
            self._emit(on_progress)
            return None

        available = is_available()
        t0 = time.perf_counter()
        result = solve(board, level(), time_limit()) if available else None
        score = 0.0
        if result is not None and result[0] in legal:
            move, score = result[0], float(result[1])
            note = "Edax 求解完成"
        else:
            move = sort_moves_by_heuristic(board, legal, self.player)[0]
            note = "Edax 未安装" if not available else "Edax 超时 / 无解，已降级"

        self.think.phase = "Edax 引擎求解"
        self.think.done = self.think.total = 1
        self.think.best_move = move
        self.think.best_value = score
        self.think.top_moves = [(move, 1, score)]
        self.think.note = note
        self.think.elapsed = time.perf_counter() - t0
        self.think.finish()
        self._emit(on_progress)
        return move
