# -*- coding: utf-8 -*-
"""
棋盘抽象基类 —— 三种棋类统一接口契约。

设计目的：
    AI 算法（MCTS / Alpha-Beta / Random）与对局控制器只面向本基类编程，
    不关心具体是五子棋、黑白棋还是围棋，从而实现「一套算法适配三种棋」。

约定：
    棋盘用二维列表表示，元素取值：
        EMPTY = 0  空位
        BLACK = 1 黑棋（先手）
        WHITE = 2 白棋（后手）
    坐标统一为 (row, col)，行列均从 0 开始。
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import List, Tuple, Optional

# 棋盘元素取值常量
EMPTY = 0
BLACK = 1
WHITE = 2

# 终局结果常量：表示「平局」（与 EMPTY 区分开，避免语义混淆）
DRAW = 3

# 方向集合（八方向，黑白棋 / 围棋气计算复用；五子棋四方向在子类内单独定义）
ALL_DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


class BaseBoard(ABC):
    """所有棋盘类的抽象父类。"""

    def __init__(self, size: int) -> None:
        # 棋盘边长（路数 / 格数）
        self.size: int = size
        # 二维棋盘矩阵
        self.board: List[List[int]] = [
            [EMPTY for _ in range(size)] for _ in range(size)
        ]
        # 当前轮到的玩家，默认黑棋先行
        self.current_player: int = BLACK
        # 最后一步落子坐标 (row, col)，用于界面高亮；无落子时为 None
        self.last_move: Optional[Tuple[int, int]] = None
        # 已落子总数
        self.move_count: int = 0
        # 对局是否已经结束
        self.game_over: bool = False
        # 终局结果：EMPTY 未分胜负；BLACK / WHITE 对应胜方；DRAW 平局
        self.winner: int = EMPTY
        # 走法历史记录，元素为 (row, col, player)
        self.history: List[Tuple[int, int, int]] = []

    # ===================== 子类必须实现的抽象接口 =====================

    @abstractmethod
    def get_legal_moves(self) -> List[Tuple[int, int]]:
        """返回当前玩家全部合法落子位置列表；无可走步时返回空列表。"""

    @abstractmethod
    def apply_move(self, move: Tuple[int, int]) -> bool:
        """
        在 move 处落子。

        返回：
            True  —— 落子成功，棋盘状态已更新；
            False —— 落子非法（位置越界 / 已有子 / 违反规则），状态保持不变。
        """

    @abstractmethod
    def _check_game_end(self) -> None:
        """落子后判断对局是否结束并更新 game_over 与 winner，由子类实现具体规则。"""

    @abstractmethod
    def copy(self) -> "BaseBoard":
        """返回当前棋盘的深拷贝（MCTS 模拟、Alpha-Beta 搜索需要在副本上推演）。"""

    # ===================== 通用工具方法（子类直接复用） =====================

    @staticmethod
    def opponent(player: int) -> int:
        """返回对手玩家编号：黑 ↔ 白。"""
        return WHITE if player == BLACK else BLACK

    def in_bounds(self, row: int, col: int) -> bool:
        """判断坐标是否在棋盘范围内。"""
        return 0 <= row < self.size and 0 <= col < self.size

    def get_piece(self, row: int, col: int) -> int:
        """读取指定位置棋子；越界返回 EMPTY。"""
        if not self.in_bounds(row, col):
            return EMPTY
        return self.board[row][col]

    def has_legal_moves(self, player: Optional[int] = None) -> bool:
        """判断指定玩家（默认当前玩家）是否存在合法落子点。"""
        if player is not None:
            # 临时切换视角统计指定玩家合法步（不改变当前状态）
            saved = self.current_player
            self.current_player = player
            result = len(self.get_legal_moves()) > 0
            self.current_player = saved
            return result
        return len(self.get_legal_moves()) > 0

    @staticmethod
    def player_label(player: int) -> str:
        """玩家编号转中文标签，用于界面与日志显示。"""
        if player == BLACK:
            return "黑方"
        if player == WHITE:
            return "白方"
        return "空"

    def _swap_player(self) -> None:
        """切换当前回合玩家。"""
        self.current_player = self.opponent(self.current_player)

    def _record_move(self, row: int, col: int, player: int) -> None:
        """记录一步走法到历史列表。"""
        self.history.append((row, col, player))

    def _base_copy_state(self, target: "BaseBoard") -> None:
        """
        把当前棋盘的通用状态深拷贝到 target，供子类 copy() 复用，
        避免重复编写 board / history 等字段的复制代码。
        """
        target.size = self.size
        target.board = deepcopy(self.board)
        target.current_player = self.current_player
        target.last_move = self.last_move
        target.move_count = self.move_count
        target.game_over = self.game_over
        target.winner = self.winner
        target.history = list(self.history)
