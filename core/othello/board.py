# -*- coding: utf-8 -*-
"""
黑白棋（Othello / Reversi）规则实现。

规则要点：
1. 棋盘默认 8×8，开局中央四格按「黑—白 / 白—黑」交叉摆放；
2. 落子必须在至少一个方向上夹住对方连续棋子，落子后该方向被夹住的
   对方棋子全部翻转为己方颜色；夹不住任何对方棋子的位置不合法；
3. 一方无合法落子点时，回合自动跳过、由另一方继续落子；
4. 双方均无合法落子点（或棋盘下满）时对局结束，棋子多的一方获胜，
   数量相同判平局。

性能设计（本轮改造）：
    合法步生成与翻子计算改为标准位板八方向移位算法。原先是「逐空格 ×
    八方向 × Python while 循环」收集翻转串，现在一次位运算扩张对手链、
    一次移位得到全部合法落点 / 翻转位集合。二维列表仍是权威表示，位板
    每次从二维列表按需构建（O(64) 整数循环），外部直接写 board.board 也安全。

    另提供 push/pop：搜索推演原地落子 + 回溯，替掉 copy() + apply_move()。
"""

from typing import List, Tuple

from core.base_board import BaseBoard, EMPTY, BLACK, WHITE, DRAW
from core.bitboard import DIRECTIONS_8, bit_count


class OthelloBoard(BaseBoard):
    """黑白棋棋盘与规则状态机。"""

    def __init__(self, size: int = 8) -> None:
        super().__init__(size)
        self._init_center_pieces()

    def _init_center_pieces(self) -> None:
        """在棋盘正中央摆放开局四枚棋子。"""
        mid = self.size // 2
        # 布局：左上白、右上黑、左下黑、右下白
        self.board[mid - 1][mid - 1] = WHITE
        self.board[mid - 1][mid] = BLACK
        self.board[mid][mid - 1] = BLACK
        self.board[mid][mid] = WHITE

    # -------------------- 位板核心 --------------------

    @staticmethod
    def _legal_mask(mine: int, opp: int, empty: int, geo) -> int:
        """
        八方向位板扩张：从己方棋子出发，沿方向连续吞并对手棋子，
        链尾之后若为空格，就是该方向上的合法落点。返回全部合法落点位集合。
        """
        result = 0
        for dr, dc in DIRECTIONS_8:
            x = geo.shift(mine, dr, dc) & opp
            if not x:
                continue
            for _ in range(6):          # 单方向最多连吃 6 枚，必然收敛
                nxt = x | (geo.shift(x, dr, dc) & opp)
                if nxt == x:
                    break
                x = nxt
            result |= geo.shift(x, dr, dc) & empty
        return result

    @staticmethod
    def _flip_mask(place: int, mine: int, opp: int, geo) -> int:
        """落子后全部被翻转的对手棋子位集合（八方向合起来）。"""
        flips = 0
        for dr, dc in DIRECTIONS_8:
            x = geo.shift(place, dr, dc) & opp
            if not x:
                continue
            chain = 0
            while x:
                chain |= x
                x = geo.shift(x, dr, dc) & opp
            # 链尾之后必须紧接己方棋子（含刚落下的这枚），否则夹吃不成立
            if geo.shift(chain, dr, dc) & mine:
                flips |= chain
        return flips

    def _bb(self):
        """(geometry, mine, opp, empty)：一次构建，供本轮规则计算复用。"""
        geo, masks = self._bitboards()
        me = self.current_player
        return geo, masks[me], masks[self.opponent(me)], masks[EMPTY]

    # -------------------- 规则接口实现 --------------------

    def get_legal_moves(self) -> List[Tuple[int, int]]:
        """返回当前玩家全部可夹住对方棋子的合法空位。"""
        geo, mine, opp, empty = self._bb()
        return geo.cells_of(self._legal_mask(mine, opp, empty, geo))

    def _flip_cells(self, row: int, col: int, player: int) -> List[Tuple[int, int]]:
        """
        假设在 (row, col) 为 player 落子，返回所有会被翻转的对方棋子坐标。
        夹不住任何对方棋子时返回空列表（即该位置不合法）。
        """
        geo, masks = self._bitboards()
        place = 1 << (row * self.size + col)
        opp = self.opponent(player)
        mine = masks[player] | place
        flips = self._flip_mask(place, mine, masks[opp], geo)
        return geo.cells_of(flips) if flips else []

    def _apply_core(self, row: int, col: int, flips) -> None:
        """落子 + 翻转 + 回合 / 终局判定（不含合法性校验）。"""
        player = self.current_player
        self.board[row][col] = player
        for fr, fc in flips:
            self.board[fr][fc] = player

        self.last_move = (row, col)
        self.move_count += 1
        self._record_move(row, col, player)

        # 切换到对方；若对方无合法步，则回合跳回己方
        self._swap_player()
        if not self.has_legal_moves():
            self._swap_player()

        # 判定双方是否都已无子可走 / 棋盘已满
        self._check_game_end()

    def _apply_unchecked(self, move) -> bool:
        """push() 用：调用方保证 move 合法，跳过重复校验但保留终局判定。"""
        row, col = move
        if self.game_over or not self.in_bounds(row, col):
            return False
        if self.board[row][col] != EMPTY:
            return False
        flips = self._flip_cells(row, col, self.current_player)
        if not flips:
            return False
        self._apply_core(row, col, flips)
        return True

    def apply_move(self, move: Tuple[int, int]) -> bool:
        """落子并翻转被夹住的棋子；非法落子返回 False 且状态不变。"""
        return self._apply_unchecked(move)

    def _check_game_end(self) -> None:
        """双方均无合法步，或棋盘已满时结束对局并按子数判定胜负。"""
        other = self.opponent(self.current_player)
        no_moves = not self.has_legal_moves() and not self.has_legal_moves(other)
        board_full = self.move_count >= self.size * self.size

        if no_moves or board_full:
            self.game_over = True
            black, white = self.count_pieces()
            if black > white:
                self.winner = BLACK
            elif white > black:
                self.winner = WHITE
            else:
                self.winner = DRAW

    def copy(self) -> "OthelloBoard":
        """深拷贝当前棋盘状态，供 AI 搜索推演使用。"""
        new_board = OthelloBoard(self.size)
        self._base_copy_state(new_board)
        return new_board

    # -------------------- 规则辅助计算 --------------------

    def count_pieces(self) -> Tuple[int, int]:
        """统计黑、白棋子数量，返回 (黑棋数, 白棋数)。"""
        _, masks = self._bitboards()
        return bit_count(masks[BLACK]), bit_count(masks[WHITE])
