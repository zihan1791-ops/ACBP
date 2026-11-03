# -*- coding: utf-8 -*-
"""随机基线 AI：从合法步中随机选择一步。

用途：
1. 跑通对局流程、验证规则与界面；
2. 作为算法 PK 的对照基线，方便观察 MCTS / Alpha-Beta 的提升效果。
"""

import random
from typing import Optional, Tuple

from .base_ai import BaseAI


class RandomAI(BaseAI):
    """随机策略 AI。"""

    name = "random"
    display_name = "随机"

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        legal = board.get_legal_moves()
        if not legal:
            return None

        self._begin_think()
        self.think.phase = "随机选步"
        move = random.choice(legal)
        self.think.best_move = move
        self.think.note = "随机基线"
        self._emit(on_progress)
        self.think.finish()
        return move
