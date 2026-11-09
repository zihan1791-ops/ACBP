# -*- coding: utf-8 -*-
"""
棋盘抽象基类 —— 四种棋类统一接口契约。

设计目的：
    AI 算法与对局控制器只面向本基类编程，不关心具体是五子棋、黑白棋、
    围棋还是中国象棋，从而实现「一套算法适配四种棋」。
    基类另提供位板几何工具与 push/pop（make/unmake）撤销栈，供规则层与
    搜索层做性能优化；二维列表 board 始终是权威表示。

约定：
    棋盘用二维列表表示，元素取值：
        EMPTY = 0  空位
        BLACK = 1 黑棋（先手）
        WHITE = 2 白棋（后手）
    坐标统一为 (row, col)，行列均从 0 开始。
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

from core.bitboard import BitboardGeometry, build_masks

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
        # make/unmake 撤销栈：搜索推演时原地落子 + 回溯，避免反复 copy()
        self._undo_stack: List[tuple] = []

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

    def _geometry(self) -> BitboardGeometry:
        """当前棋盘尺寸对应的位板几何表（按尺寸全局缓存，只算一次）。"""
        rows = len(self.board)
        cols = len(self.board[0]) if rows else 0
        return BitboardGeometry(rows, cols)

    def _bitboards(self):
        """
        从权威二维列表构建位板，返回 (geometry, {取值: 位板})。

        位板是按需构建的局部加速结构，不持久化 —— 这样外部代码直接写
        board.board（试探性落子、测试构造局面）也不会造成状态失同步。
        """
        rows = len(self.board)
        cols = len(self.board[0]) if rows else 0
        return build_masks(self.board, rows, cols)

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

    # ===================== make / unmake（搜索推演专用） =====================
    #
    # 原先 AI 每推演一步都要 `child = board.copy(); child.apply_move(move)`：
    # 既要构造新棋盘对象（象棋构造器还会重摆 32 枚棋子），又要在 apply_move
    # 里重复做一次完整合法性校验。push/pop 把两件事都省掉——原地改棋盘，
    # 用一份轻量快照回溯。二维列表仍是权威表示，快照用行拷贝即可。

    def _apply_unchecked(self, move) -> bool:
        """
        跳过合法性校验的落子（含终局判定），由子类实现。
        调用方必须保证 move 来自当前局面的合法步集合。
        """
        return self.apply_move(move)

    def _snapshot(self) -> tuple:
        """捕获可回溯状态；子类有额外字段时在末尾追加并覆盖 _restore。"""
        return ([row[:] for row in self.board],
                self.current_player, self.last_move, self.move_count,
                self.game_over, self.winner, len(self.history))

    def _restore(self, snap: tuple) -> None:
        rows, player, last, count, over, winner, hist_len = snap[:7]
        self.board = rows
        self.current_player = player
        self.last_move = last
        self.move_count = count
        self.game_over = over
        self.winner = winner
        if len(self.history) > hist_len:
            del self.history[hist_len:]

    def push(self, move) -> bool:
        """原地落子并压栈；返回 False 表示落子失败且状态未改变。"""
        snap = self._snapshot()
        if not self._apply_unchecked(move):
            return False
        self._undo_stack.append(snap)
        return True

    def pop(self) -> bool:
        """撤销最近一次 push，完整还原棋盘与对局状态。"""
        if not self._undo_stack:
            return False
        self._restore(self._undo_stack.pop())
        return True

    @property
    def undo_depth(self) -> int:
        return len(self._undo_stack)

    def _base_copy_state(self, target: "BaseBoard") -> None:
        """
        把当前棋盘的通用状态深拷贝到 target，供子类 copy() 复用，
        避免重复编写 board / history 等字段的复制代码。
        """
        target.size = self.size
        # 行拷贝比 deepcopy 快数倍：棋盘元素均为不可变整数，无需递归复制
        target.board = [row[:] for row in self.board]
        target.current_player = self.current_player
        target.last_move = self.last_move
        target.move_count = self.move_count
        target.game_over = self.game_over
        target.winner = self.winner
        target.history = list(self.history)
