# -*- coding: utf-8 -*-
"""
棋盘视图（BoardView）—— 编辑式棋谱刊物中的「版面棋盘」。

职责与坐标换算逻辑保持原样（这是与规则层的契约，不能改）：
    _layout / cell_center / pixel_to_cell / _is_intersection_board
    draw(surface, show_legal_hint=False) / draw_candidate_marks(surface, top_moves)

视觉重设计：
1. 棋墩纸底 + 双线装帧外框，四边印等宽坐标（A… / 15…01），像印出来的棋谱图；
2. 网格用发丝墨线，外框线略重；星位改成小十字而非圆点；
3. 棋子去掉塑料高光：黑子实墨 + 描边，白子纸白 + 细墨圈；
4. 最后一手用朱砂四角括号定位，合法点用淡墨小点，AI 候选带等宽序号。
"""

import pygame
from typing import Optional, Tuple

from . import theme, assets, atmosphere, piece_skins
from core.base_board import EMPTY, BLACK


class BoardView:
    """单块棋盘的绘制与坐标换算组件。"""

    def __init__(self, rect, board, skins=None) -> None:
        self.rect = pygame.Rect(rect)
        self.board = board
        self.skins = {}
        self.set_skins(skins)
        self._coord_key = None
        self._coord_items = []
        self._layout()

    def set_skins(self, skins=None) -> None:
        """更新双方棋子外观映射（键为 BLACK / WHITE）。"""
        self.skins = dict(skins or {})

    # ===================== 布局计算（契约，逻辑不变） =====================

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

    # ===================== 坐标标注（预渲染缓存） =====================

    def _prepare_coords(self) -> None:
        """棋谱坐标只在布局变化时重建，避免 AI 高频重绘时反复渲染文字。"""
        key = (self.board.size, round(self.cell, 2),
               round(self.origin_x, 1), round(self.origin_y, 1))
        if self._coord_key == key:
            return
        self._coord_key = key
        n = self.board.size
        size = theme.S(14)
        f = assets.font("mono", size)
        items = []
        # 坐标是信息文字，用 INK_SOFT 而非仅装饰用的 INK_FAINT
        for i in range(n):
            col = f.render(chr(65 + i) if i < 26 else str(i), True, theme.INK_SOFT)
            items.append((col, (self.origin_x + i * self.cell - col.get_width() / 2,
                                self.origin_y - theme.S(30))))
            row = f.render("%02d" % (n - i), True, theme.INK_SOFT)
            items.append((row, (self.origin_x - theme.S(42) - row.get_width() / 2,
                                self.origin_y + i * self.cell - row.get_height() / 2)))
        self._coord_items = items

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface, show_legal_hint: bool = False) -> None:
        """绘制完整棋盘：装帧 → 坐标 → 网格 → 合法提示 → 棋子 → 最后一手。"""
        s = theme.S
        pygame.draw.rect(surface, theme.BOARD_PAPER, self.rect,
                         border_radius=theme.RADIUS)
        pygame.draw.rect(surface, theme.RULE, self.rect,
                         width=1, border_radius=theme.RADIUS)
        inner = self.rect.inflate(-s(8), -s(8))
        pygame.draw.rect(surface, theme.RULE_LIGHT, inner,
                         width=1, border_radius=theme.RADIUS)

        self._prepare_coords()
        for glyph, pos in self._coord_items:
            surface.blit(glyph, (int(pos[0]), int(pos[1])))

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
        """交叉点棋盘：外框线略重，内部发丝线。"""
        n = self.board.size
        end = n - 1
        for i in range(n):
            x = self.origin_x + i * self.cell
            y = self.origin_y + i * self.cell
            color = theme.INK_SOFT if i in (0, end) else theme.RULE
            width = 2 if i in (0, end) else 1
            pygame.draw.line(surface, color, (x, self.origin_y),
                             (x, self.origin_y + end * self.cell), width)
            pygame.draw.line(surface, color, (self.origin_x, y),
                             (self.origin_x + end * self.cell, y), width)

    def _draw_square_lines(self, surface: pygame.Surface) -> None:
        """黑白棋方格棋盘：细墨分格线。"""
        n = self.board.size
        for i in range(n + 1):
            x = self.origin_x + i * self.cell
            y = self.origin_y + i * self.cell
            pygame.draw.line(surface, theme.RULE, (x, self.origin_y),
                             (x, self.origin_y + n * self.cell))
            pygame.draw.line(surface, theme.RULE, (self.origin_x, y),
                             (self.origin_x + n * self.cell, y))

    def _draw_star_points(self, surface: pygame.Surface) -> None:
        """星位改画成小十字，比圆点更贴印刷棋谱图。"""
        n = self.board.size
        if n == 15:
            points = [(3, 3), (3, 11), (7, 7), (11, 3), (11, 11)]
        elif n == 9:
            points = [(2, 2), (2, 6), (4, 4), (6, 2), (6, 6)]
        else:
            return
        arm = max(theme.S(3), int(self.cell * 0.10))
        for r, c in points:
            x, y = self.cell_center(r, c)
            x, y = int(x), int(y)
            pygame.draw.line(surface, theme.STAR_POINT,
                             (x - arm, y), (x + arm, y), 1)
            pygame.draw.line(surface, theme.STAR_POINT,
                             (x, y - arm), (x, y + arm), 1)

    def _draw_legal_hints(self, surface: pygame.Surface) -> None:
        """人类回合：在合法空位上点一个淡墨小点，不抢棋子注意力。"""
        r = max(theme.S(2), int(self.cell * 0.07))
        for row, col in self.board.get_legal_moves():
            x, y = self.cell_center(row, col)
            pygame.draw.circle(surface, theme.INK_FAINT, (int(x), int(y)), r)

    def _draw_all_stones(self, surface: pygame.Surface) -> None:
        n = self.board.size
        for r in range(n):
            for c in range(n):
                piece = self.board.board[r][c]
                if piece != EMPTY:
                    self._draw_stone(surface, r, c, piece)

    def _draw_stone(self, surface: pygame.Surface,
                    row: int, col: int, piece: int) -> None:
        """棋子：有头像时整颗贴 PNG，classic 或缺图时画纯色棋子。"""
        x, y = self.cell_center(row, col)
        radius = int(self.cell * 0.42)
        off = max(theme.S(2), int(self.cell * 0.045))
        pygame.draw.circle(surface, theme.STONE_SHADOW,
                           (int(x + off), int(y + off)), radius)

        black = piece == BLACK
        cx, cy = int(x), int(y)
        skin = self.skins.get(piece)

        # 整图版：棋子就是这张 PNG，铺满直径，不加底色也不加描边
        face_size = max(8, 2 * radius)
        face = piece_skins.face(skin, face_size) if skin else None

        if face is None:
            pygame.draw.circle(surface,
                               theme.BLACK_STONE if black else theme.WHITE_STONE,
                               (cx, cy), radius)
            pygame.draw.circle(surface,
                               theme.STONE_HIGHLIGHT if black else theme.RULE,
                               (cx, cy), radius, 1)
            return

        # 圆形裁切已在 ui/piece_skins 完成，这里直接贴图
        surface.blit(face, face.get_rect(center=(cx, cy)))

    def _draw_last_move(self, surface: pygame.Surface) -> None:
        """最后一手用朱砂四角括号定位，而不是盖住棋子的圆环。"""
        if self.board.last_move is None:
            return
        r, c = self.board.last_move
        x, y = self.cell_center(r, c)
        side = int(self.cell * 0.74)
        box = pygame.Rect(int(x - side / 2), int(y - side / 2), side, side)
        length = max(4, int(self.cell * 0.12))
        # 先铺一圈纸白粗括号做外描边，再压朱砂细括号；在深发色上仍可辨认
        atmosphere.brackets(surface, box.inflate(theme.S(2), theme.S(2)),
                            theme.PAPER, length, 4)
        atmosphere.brackets(surface, box, theme.CINNABAR, length, 2)

    def draw_candidate_marks(self, surface: pygame.Surface, top_moves) -> None:
        """
        在棋盘上高亮 AI 正在评估的候选走法，并印上等宽序号。
        第 1 名朱砂实心，其余灰墨空心 —— 单强调色纪律。
        """
        s = theme.S
        for idx, item in enumerate(top_moves[:3]):
            move = item[0]
            if move is None or not self.board.in_bounds(*move):
                continue
            x, y = self.cell_center(move[0], move[1])
            x, y = int(x), int(y)
            radius = int(self.cell * (0.24 if idx == 0 else 0.20))
            if idx == 0:
                pygame.draw.circle(surface, theme.CINNABAR, (x, y), radius)
                num_color = theme.PAPER_ON_RED
            else:
                pygame.draw.circle(surface, theme.SURFACE, (x, y), radius)
                pygame.draw.circle(surface, theme.INK_SOFT, (x, y), radius, 1)
                num_color = theme.INK
            num = assets.font("mono", s(14)).render(str(idx + 1), True, num_color)
            surface.blit(num, num.get_rect(center=(x, y)))
