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
"""

from typing import List, Tuple

from core.base_board import BaseBoard, EMPTY, BLACK, WHITE, DRAW, ALL_DIRECTIONS


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

    # -------------------- 规则接口实现 --------------------

    def get_legal_moves(self) -> List[Tuple[int, int]]:
        """返回当前玩家全部可夹住对方棋子的合法空位。"""
        moves: List[Tuple[int, int]] = []
        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] == EMPTY and self._flip_cells(r, c, self.current_player):
                    moves.append((r, c))
        return moves

    def apply_move(self, move: Tuple[int, int]) -> bool:
        """落子并翻转被夹住的棋子；非法落子返回 False 且状态不变。"""
        row, col = move

        if self.game_over:
            return False
        if not self.in_bounds(row, col):
            return False
        if self.board[row][col] != EMPTY:
            return False

        flips = self._flip_cells(row, col, self.current_player)
        if not flips:
            # 该位置夹不住对方棋子，不合法
            return False

        # 落子并翻转全部被夹住的对方棋子
        self.board[row][col] = self.current_player
        for fr, fc in flips:
            self.board[fr][fc] = self.current_player

        self.last_move = (row, col)
        self.move_count += 1
        self._record_move(row, col, self.current_player)

        # 切换到对方；若对方无合法步，则回合跳回己方
        self._swap_player()
        if not self.has_legal_moves():
            self._swap_player()

        # 判定双方是否都已无子可走 / 棋盘已满
        self._check_game_end()
        return True

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

    def _flip_cells(self, row: int, col: int, player: int) -> List[Tuple[int, int]]:
        """
        假设在 (row, col) 为 player 落子，收集所有会被翻转的对方棋子坐标。
        若该位置不合法（夹不住任何对方棋子），返回空列表。
        """
        opponent = self.opponent(player)
        flips: List[Tuple[int, int]] = []

        for dr, dc in ALL_DIRECTIONS:
            line: List[Tuple[int, int]] = []
            r, c = row + dr, col + dc
            # 沿方向连续收集对方棋子
            while self.in_bounds(r, c) and self.board[r][c] == opponent:
                line.append((r, c))
                r += dr
                c += dc
            # 收集到至少一枚对方棋子，且方向末端是己方棋子，才形成夹吃
            if line and self.in_bounds(r, c) and self.board[r][c] == player:
                flips.extend(line)
        return flips

    def count_pieces(self) -> Tuple[int, int]:
        """统计黑、白棋子数量，返回 (黑棋数, 白棋数)。"""
        black = white = 0
        for row in self.board:
            for cell in row:
                if cell == BLACK:
                    black += 1
                elif cell == WHITE:
                    white += 1
        return black, white
