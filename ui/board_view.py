# -*- coding: utf-8 -*-
"""
棋盘视图（BoardView）。

职责：
1. 根据棋盘类型绘制网格 / 方格、星点、棋子与最后一手标记；
2. 完成「像素坐标 ↔ 棋盘行列坐标」互转，供鼠标点击落子使用；
3. 可选地为当前人类回合高亮提示合法落子点。

五子棋、围棋为「交叉点棋盘」，黑白棋为「方格棋盘」，两类布局在内部自动区分。
"""

import pygame
from typing import Optional, Tuple

from . import theme
from core.base_board import EMPTY, BLACK


class BoardView:
    """单块棋盘的绘制与坐标换算组件。"""

    def __init__(self, rect, board) -> None:
        self.rect = pygame.Rect(rect)
        self.board = board
        self._layout()

    # ===================== 布局计算 =====================

    def _layout(self) -> None:
        """根据棋盘尺寸与视图矩形计算格距、原点坐标，保证棋盘居中。"""
        n = self.board.size
        available_w = self.rect.width - theme.BOARD_MARGIN * 2
        available_h = self.rect.height - theme.BOARD_MARGIN * 2
        self.cell = min(available_w / n, available_h / n)

        grid_w = self.cell * n
        self.origin_x = self.rect.centerx - grid_w / 2
        self.origin_y = self.rect.centery - grid_w / 2

    @property
    def _is_intersection_board(self) -> bool:
        """是否为交叉点棋盘（五子棋 / 围棋）；黑白棋为方格棋盘。"""
        return type(self.board).__name__ != "OthelloBoard"

    def cell_center(self, row: int, col: int) -> Tuple[float, float]:
        """返回 (row, col) 对应棋子在视图中的像素中心坐标。"""
        if self._is_intersection_board:
            x = self.origin_x + col * self.cell
            y = self.origin_y + row * self.cell
        else:
            x = self.origin_x + (col + 0.5) * self.cell
            y = self.origin_y + (row + 0.5) * self.cell
        return x, y

    def pixel_to_cell(self, pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """把鼠标像素坐标换算为棋盘行列；越界返回 None。"""
        x, y = pos
        if self._is_intersection_board:
            col = round((x - self.origin_x) / self.cell)
            row = round((y - self.origin_y) / self.cell)
        else:
            col = int((x - self.origin_x) / self.cell)
            row = int((y - self.origin_y) / self.cell)
        if self.board.in_bounds(row, col):
            return row, col
        return None

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface, show_legal_hint: bool = False) -> None:
        """绘制完整棋盘：底色 → 网格 → 合法提示 → 棋子 → 最后一手标记。"""
        # 棋盘底色圆角矩形
        pygame.draw.rect(surface, theme.BOARD_BG, self.rect, border_radius=theme.RADIUS)

        if self._is_intersection_board:
            self._draw_grid_lines(surface)
            self._draw_star_points(surface)
        else:
            self._draw_square_lines(surface)

        if show_legal_hint:
            self._draw_legal_hints(surface)

        self._draw_all_stones(surface)
        self._draw_last_move(surface)

    def _draw_grid_lines(self, surface: pygame.Surface) -> None:
        """绘制交叉点棋盘的横竖网格线。"""
        n = self.board.size
        end = n - 1
        for i in range(n):
            x = self.origin_x + i * self.cell
            y = self.origin_y + i * self.cell
            pygame.draw.line(surface, theme.GRID,
                             (x, self.origin_y), (x, self.origin_y + end * self.cell), 1)
            pygame.draw.line(surface, theme.GRID,
                             (self.origin_x, y), (self.origin_x + end * self.cell, y), 1)

    def _draw_square_lines(self, surface: pygame.Surface) -> None:
        """绘制黑白棋方格棋盘的分格线。"""
        n = self.board.size
        for i in range(n + 1):
            x = self.origin_x + i * self.cell
            y = self.origin_y + i * self.cell
            pygame.draw.line(surface, theme.GRID,
                             (x, self.origin_y), (x, self.origin_y + n * self.cell), 1)
            pygame.draw.line(surface, theme.GRID,
                             (self.origin_x, y), (self.origin_x + n * self.cell, y), 1)

    def _draw_star_points(self, surface: pygame.Surface) -> None:
        """绘制交叉点棋盘星位（15 路五子棋与 9 路围棋使用经典星点位置）。"""
        n = self.board.size
        if n == 15:
            points = [(3, 3), (3, 11), (7, 7), (11, 3), (11, 11)]
        elif n == 9:
            points = [(2, 2), (2, 6), (4, 4), (6, 2), (6, 6)]
        else:
            return
        for r, c in points:
            x, y = self.cell_center(r, c)
            pygame.draw.circle(surface, theme.STAR_POINT, (int(x), int(y)), theme.S(3))

    def _draw_legal_hints(self, surface: pygame.Surface) -> None:
        """在当前合法空位上绘制淡绿色小圆点，提示人类可落子位置。"""
        for r, c in self.board.get_legal_moves():
            x, y = self.cell_center(r, c)
            pygame.draw.circle(surface, theme.ACCENT, (int(x), int(y)), theme.S(4))

    def _draw_all_stones(self, surface: pygame.Surface) -> None:
        """遍历棋盘绘制全部棋子。"""
        n = self.board.size
        for r in range(n):
            for c in range(n):
                piece = self.board.board[r][c]
                if piece != EMPTY:
                    self._draw_stone(surface, r, c, piece)

    def _draw_stone(self, surface: pygame.Surface, row: int, col: int, piece: int) -> None:
        """绘制单枚棋子：柔和投影 + 圆形主体 + 顶部高光。"""
        x, y = self.cell_center(row, col)
        radius = int(self.cell * 0.42)

        # 投影（向右下轻微偏移）
        shadow_offset = max(theme.S(2), int(self.cell * 0.06))
        pygame.draw.circle(surface, theme.STONE_SHADOW,
                           (int(x + shadow_offset), int(y + shadow_offset)), radius)

        # 棋子主体
        stone_color = theme.BLACK_STONE if piece == BLACK else theme.WHITE_STONE
        pygame.draw.circle(surface, stone_color, (int(x), int(y)), radius)

        # 顶部高光（白色小椭圆，营造圆润质感）
        highlight_r = int(radius * 0.45)
        pygame.draw.ellipse(
            surface, theme.STONE_HIGHLIGHT if piece == BLACK else (225, 225, 225),
            (int(x - highlight_r), int(y - highlight_r),
             highlight_r * 2, int(highlight_r * 1.2)))

    def _draw_last_move(self, surface: pygame.Surface) -> None:
        """在最后一手棋子上绘制红棕色圆环标记，便于追踪最近落子。"""
        if self.board.last_move is None:
            return
        r, c = self.board.last_move
        x, y = self.cell_center(r, c)
        pygame.draw.circle(surface, theme.WARN, (int(x), int(y)),
                           int(self.cell * 0.18), 2)

    def draw_candidate_marks(self, surface: pygame.Surface, top_moves) -> None:
        """
        在棋盘上高亮 AI 正在评估的候选走法（思考可视化）。

        参数：
            top_moves: 思考状态中的 Top 候选列表，元素为 (坐标, 访问数/序, 胜率/分值)；
                       第 1 名用强调色大点，第 2~3 名用辅助蓝小点。
        """
        for idx, item in enumerate(top_moves[:3]):
            move = item[0]
            if move is None or not self.board.in_bounds(*move):
                continue
            x, y = self.cell_center(move[0], move[1])
            if idx == 0:
                pygame.draw.circle(surface, theme.ACCENT, (int(x), int(y)),
                                   int(self.cell * 0.28))
                pygame.draw.circle(surface, theme.TEXT_ON_ACCENT, (int(x), int(y)),
                                   int(self.cell * 0.28), 2)
            else:
                pygame.draw.circle(surface, theme.BLUE, (int(x), int(y)),
                                   int(self.cell * 0.20))
                pygame.draw.circle(surface, theme.PANEL, (int(x), int(y)),
                                   int(self.cell * 0.20), 1)
