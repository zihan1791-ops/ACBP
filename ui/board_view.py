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

皮肤支持（本轮新增）：
    所有颜色改从 ui/skins.py 取令牌；棋盘底与棋子本体可用 PNG 贴图。
    默认皮肤 paper / classic 无贴图，完全走原有纯代码绘制，观感不变；
    贴图缺失 / 损坏时 board_texture / stone_texture 返回 None，自动回退。
    贴图按皮肤 id 与尺寸缓存，AI 思考期高频重绘不会反复缩放图片。
"""

import pygame
from typing import Optional, Tuple

from . import theme, assets, atmosphere, skins
from core.base_board import EMPTY, BLACK


class BoardView:
    """单块棋盘的绘制与坐标换算组件。"""

    def __init__(self, rect, board) -> None:
        self.rect = pygame.Rect(rect)
        self.board = board
        self._coord_key = None
        self._coord_items = []
        self._bg_key = None
        self._bg_surf = None
        self._layout()

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

    def _prepare_coords(self, pal: dict, board_id: str) -> None:
        """棋谱坐标只在布局或皮肤变化时重建，避免 AI 高频重绘反复渲染文字。"""
        key = (self.board.size, round(self.cell, 2),
               round(self.origin_x, 1), round(self.origin_y, 1),
               board_id, pal["coord"])
        if self._coord_key == key:
            return
        self._coord_key = key
        n = self.board.size
        size = theme.S(14)
        f = assets.font("mono", size)
        items = []
        # 坐标是信息文字，颜色随皮肤（深色棋盘上自动换成浅字）
        color = pal["coord"]
        for i in range(n):
            col = f.render(chr(65 + i) if i < 26 else str(i), True, color)
            items.append((col, (self.origin_x + i * self.cell - col.get_width() / 2,
                                self.origin_y - theme.S(30))))
            row = f.render("%02d" % (n - i), True, color)
            items.append((row, (self.origin_x - theme.S(42) - row.get_width() / 2,
                                self.origin_y + i * self.cell - row.get_height() / 2)))
        self._coord_items = items

    # ===================== 棋盘底（贴图缓存） =====================

    def _background(self, board_id: str) -> Optional[pygame.Surface]:
        """返回带圆角的棋盘底贴图；无贴图皮肤返回 None（由 draw 画纯色）。"""
        key = (self.rect.width, self.rect.height, board_id, theme.RADIUS)
        if self._bg_key == key:
            return self._bg_surf
        tex = skins.board_texture(self.rect.width, self.rect.height, board_id)
        result = None
        if tex is not None:
            w, h = self.rect.width, self.rect.height
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            surf.blit(tex, (0, 0))
            mask = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255),
                             mask.get_rect(), border_radius=theme.RADIUS)
            surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            result = surf
        self._bg_key = key
        self._bg_surf = result
        return result

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface, show_legal_hint: bool = False) -> None:
        """绘制完整棋盘：装帧 → 坐标 → 网格 → 合法提示 → 棋子 → 最后一手。"""
        s = theme.S
        board_id = skins.get_board_skin()
        pal = skins.board_palette(board_id)
        sp = skins.stone_palette()

        background = self._background(board_id)
        if background is not None:
            surface.blit(background, self.rect.topleft)
        else:
            pygame.draw.rect(surface, pal["bg"], self.rect,
                             border_radius=theme.RADIUS)
        pygame.draw.rect(surface, pal["frame"], self.rect,
                         width=1, border_radius=theme.RADIUS)
        inner = self.rect.inflate(-s(8), -s(8))
        pygame.draw.rect(surface, pal["frame_inner"], inner,
                         width=1, border_radius=theme.RADIUS)

        self._prepare_coords(pal, board_id)
        for glyph, pos in self._coord_items:
            surface.blit(glyph, (int(pos[0]), int(pos[1])))

        if self._is_intersection_board:
            self._draw_grid_lines(surface, pal)
            self._draw_star_points(surface, pal)
        else:
            self._draw_square_lines(surface, pal)

        if show_legal_hint:
            self._draw_legal_hints(surface, pal)

        self._draw_all_stones(surface, sp, pal)
        self._draw_last_move(surface, pal)

    def _draw_grid_lines(self, surface: pygame.Surface, pal: dict) -> None:
        """交叉点棋盘：外框线略重，内部发丝线。"""
        n = self.board.size
        end = n - 1
        for i in range(n):
            x = self.origin_x + i * self.cell
            y = self.origin_y + i * self.cell
            color = pal["grid_outer"] if i in (0, end) else pal["grid"]
            width = 2 if i in (0, end) else 1
            pygame.draw.line(surface, color, (x, self.origin_y),
                             (x, self.origin_y + end * self.cell), width)
            pygame.draw.line(surface, color, (self.origin_x, y),
                             (self.origin_x + end * self.cell, y), width)

    def _draw_square_lines(self, surface: pygame.Surface, pal: dict) -> None:
        """黑白棋方格棋盘：细墨分格线。"""
        n = self.board.size
        for i in range(n + 1):
            x = self.origin_x + i * self.cell
            y = self.origin_y + i * self.cell
            pygame.draw.line(surface, pal["grid"], (x, self.origin_y),
                             (x, self.origin_y + n * self.cell))
            pygame.draw.line(surface, pal["grid"], (self.origin_x, y),
                             (self.origin_x + n * self.cell, y))

    def _draw_star_points(self, surface: pygame.Surface, pal: dict) -> None:
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
            pygame.draw.line(surface, pal["star"],
                             (x - arm, y), (x + arm, y), 1)
            pygame.draw.line(surface, pal["star"],
                             (x, y - arm), (x, y + arm), 1)

    def _draw_legal_hints(self, surface: pygame.Surface, pal: dict) -> None:
        """人类回合：在合法空位上点一个淡墨小点，不抢棋子注意力。"""
        r = max(theme.S(2), int(self.cell * 0.07))
        for row, col in self.board.get_legal_moves():
            x, y = self.cell_center(row, col)
            pygame.draw.circle(surface, pal["hint"], (int(x), int(y)), r)

    def _draw_all_stones(self, surface: pygame.Surface,
                         sp: dict, pal: dict) -> None:
        n = self.board.size
        for r in range(n):
            for c in range(n):
                piece = self.board.board[r][c]
                if piece != EMPTY:
                    self._draw_stone(surface, r, c, piece, sp, pal)

    def _draw_stone(self, surface: pygame.Surface,
                    row: int, col: int, piece: int,
                    sp: dict, pal: dict) -> None:
        """棋子：落子投影（随棋盘底色）+ 贴图（或实墨 / 纸白圆 + 细描边）。"""
        x, y = self.cell_center(row, col)
        radius = int(self.cell * 0.42)
        off = max(theme.S(2), int(self.cell * 0.045))
        pygame.draw.circle(surface, pal["stone_shadow"],
                           (int(x + off), int(y + off)), radius)

        black = piece == BLACK
        tex = skins.stone_texture(black, radius * 2 + 1)
        if tex is not None:
            surface.blit(tex, (int(x) - radius, int(y) - radius))
        else:
            pygame.draw.circle(surface,
                               sp["black"] if black else sp["white"],
                               (int(x), int(y)), radius)
            pygame.draw.circle(surface,
                               sp["black_rim"] if black else sp["white_rim"],
                               (int(x), int(y)), radius, 1)

    def _draw_last_move(self, surface: pygame.Surface, pal: dict) -> None:
        """最后一手用朱砂四角括号定位，而不是盖住棋子的圆环。"""
        if self.board.last_move is None:
            return
        r, c = self.board.last_move
        x, y = self.cell_center(r, c)
        side = int(self.cell * 0.74)
        box = pygame.Rect(int(x - side / 2), int(y - side / 2), side, side)
        atmosphere.brackets(surface, box, pal["accent"],
                            max(4, int(self.cell * 0.12)), 2)

    def draw_candidate_marks(self, surface: pygame.Surface, top_moves) -> None:
        """
        在棋盘上高亮 AI 正在评估的候选走法，并印上等宽序号。
        第 1 名朱砂实心，其余灰墨空心 —— 单强调色纪律。
        """
        s = theme.S
        pal = skins.board_palette()
        for idx, item in enumerate(top_moves[:3]):
            move = item[0]
            if move is None or not self.board.in_bounds(*move):
                continue
            x, y = self.cell_center(move[0], move[1])
            x, y = int(x), int(y)
            radius = int(self.cell * (0.24 if idx == 0 else 0.20))
            if idx == 0:
                pygame.draw.circle(surface, pal["accent"], (x, y), radius)
                num_color = pal["accent_fg"]
            else:
                pygame.draw.circle(surface, pal["mark_bg"], (x, y), radius)
                pygame.draw.circle(surface, pal["mark_ring"], (x, y), radius, 1)
                num_color = pal["mark_text"]
            num = assets.font("mono", s(14)).render(str(idx + 1), True, num_color)
            surface.blit(num, num.get_rect(center=(x, y)))
