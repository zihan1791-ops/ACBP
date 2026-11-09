# -*- coding: utf-8 -*-
"""
五子棋（Gomoku）规则实现。

规则要点：
1. 黑棋先行，双方轮流在棋盘交叉点空位落子；
2. 任意一方率先在横、竖、斜任意方向形成连续五枚同色棋子即获胜；
3. 棋盘下满仍未连成五子则判平局；
4. 本实现不设置「禁手」规则，属于大众休闲五子棋口径。
"""

from typing import List, Tuple

from core.base_board import BaseBoard, EMPTY, BLACK, WHITE, DRAW


class GomokuBoard(BaseBoard):
    """五子棋棋盘与规则状态机。"""

    # 五子棋只需要检查四个连线方向（水平、垂直、两条斜线）
    _DIRECTIONS = [
        (0, 1),   # 水平
        (1, 0),   # 垂直
        (1, 1),   # 主斜线（左上 → 右下）
        (1, -1),  # 副斜线（右上 → 左下）
    ]

    def __init__(self, size: int = 15) -> None:
        super().__init__(size)

    # -------------------- 规则接口实现 --------------------

    def get_legal_moves(self) -> List[Tuple[int, int]]:
        """
        返回当前全部空位作为合法落子点。

        说明：五子棋在空位落子均合法；为提升 AI 搜索效率，AI 层会在这些
        候选点中按「已有棋子邻域」重新排序，规则层保持简单清晰。
        """
        moves: List[Tuple[int, int]] = []
        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] == EMPTY:
                    moves.append((r, c))
        return moves

    def _apply_unchecked(self, move) -> bool:
        """
        push() 用：调用方已保证 move 合法，跳过重复校验但保留终局判定。
        五子棋落子本身就是 O(1) 数组写入，主要省掉的是 copy() 对象构造。
        """
        row, col = move
        if self.game_over or not self.in_bounds(row, col):
            return False
        if self.board[row][col] != EMPTY:
            return False
        self.board[row][col] = self.current_player
        self.last_move = (row, col)
        self.move_count += 1
        self._record_move(row, col, self.current_player)
        self._check_game_end()
        if not self.game_over:
            self._swap_player()
        return True

    def apply_move(self, move: Tuple[int, int]) -> bool:
        """在指定位置落子，成功返回 True；非法落子返回 False 且不改变状态。"""
        return self._apply_unchecked(move)

    def _check_game_end(self) -> None:
        """检查最后一手是否连成五子；棋盘下满则判平局。"""
        row, col = self.last_move  # type: ignore[misc]
        player = self.board[row][col]

        if self._count_line(row, col, player) >= 5:
            self.game_over = True
            self.winner = player
            return

        # 棋盘已满：平局
        if self.move_count >= self.size * self.size:
            self.game_over = True
            self.winner = DRAW

    def copy(self) -> "GomokuBoard":
        """深拷贝一份当前棋盘状态，供 AI 搜索在副本上推演。"""
        new_board = GomokuBoard(self.size)
        self._base_copy_state(new_board)
        return new_board

    # -------------------- 规则辅助计算 --------------------

    def _count_line(self, row: int, col: int, player: int) -> int:
        """
        从 (row, col) 出发，统计四个方向上与 player 连成一线的最长连续棋子数。
        每个方向向正、反两个方向延伸计数后相加，再计入当前棋子本身。
        """
        best = 1  # 当前棋子自己占 1 枚
        for dr, dc in self._DIRECTIONS:
            count = 1  # 当前棋子
            # 正方向延伸
            r, c = row + dr, col + dc
            while self.in_bounds(r, c) and self.board[r][c] == player:
                count += 1
                r += dr
                c += dc
            # 反方向延伸
            r, c = row - dr, col - dc
            while self.in_bounds(r, c) and self.board[r][c] == player:
                count += 1
                r -= dr
                c -= dc
            best = max(best, count)
        return best

    def count_pieces(self) -> Tuple[int, int]:
        """统计当前黑、白棋子数量，返回 (黑棋数, 白棋数)。"""
        black = white = 0
        for row in self.board:
            for cell in row:
                if cell == BLACK:
                    black += 1
                elif cell == WHITE:
                    white += 1
        return black, white
