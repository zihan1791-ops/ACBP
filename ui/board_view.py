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
        available_w = self.rect.width - theme.BOARD_MARGIN * 2
        available_h = self.rect.height - theme.BOARD_MARGIN * 2
        n = self.board.size
        if self._is_chess:
            rows, cols = self.board.rows, self.board.cols
            self.cell = min(available_w / cols, available_h / rows)
            self.origin_x = self.rect.centerx - self.cell * cols / 2
            self.origin_y = self.rect.centery - self.cell * rows / 2
            return
        self.cell = min(available_w / n, available_h / n)
        grid_w = self.cell * n
        self.origin_x = self.rect.centerx - grid_w / 2
        self.origin_y = self.rect.centery - grid_w / 2

    @property
    def _is_chess(self) -> bool:
        return type(self.board).__name__ == "ChessBoard"

    def _grid_shape(self):
        if self._is_chess:
            return self.board.rows, self.board.cols
        return self.board.size, self.board.size

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
        rows, cols = self._grid_shape()
        size = theme.S(14)
        f = assets.font("mono", size)
        items = []
        # 坐标是信息文字，用 INK_SOFT 而非仅装饰用的 INK_FAINT
        for i in range(cols):
            col = f.render(chr(65 + i) if i < 26 else str(i), True, theme.INK_SOFT)
            items.append((col, (self.origin_x + i * self.cell - col.get_width() / 2,
                                self.origin_y - theme.S(30))))
        for i in range(rows):
            row = f.render("%02d" % (rows - i), True, theme.INK_SOFT)
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

        # 象棋的走子轨迹画在棋子之下，避免线压在棋子上
        if self._is_chess:
            self._draw_chess_move_path(surface)
        self._draw_all_stones(surface)
        self._draw_last_move(surface)

    def _draw_grid_lines(self, surface: pygame.Surface) -> None:
        """交叉点棋盘：外框线略重，内部发丝线；象棋走专用版式。"""
        rows, cols = self._grid_shape()
        max_x = self.origin_x + (cols - 1) * self.cell
        max_y = self.origin_y + (rows - 1) * self.cell
        if self._is_chess:
            self._draw_chess_grid(surface, rows, cols, max_x, max_y)
            return
        for c in range(cols):
            x = self.origin_x + c * self.cell
            color = theme.INK_SOFT if c in (0, cols - 1) else theme.RULE
            width = 2 if c in (0, cols - 1) else 1
            pygame.draw.line(surface, color, (x, self.origin_y), (x, max_y), width)
        for r in range(rows):
            y = self.origin_y + r * self.cell
            color = theme.INK_SOFT if r in (0, rows - 1) else theme.RULE
            width = 2 if r in (0, rows - 1) else 1
            pygame.draw.line(surface, color, (self.origin_x, y), (max_x, y), width)

    # -------------------- 中国象棋专用版式 --------------------

    def _draw_chess_grid(self, surface, rows, cols, max_x, max_y) -> None:
        """
        传统象棋盘：
        · 10 条横线贯通，左右两条边线贯通；中间 7 条竖线在楚河汉界处断开；
        · 上下九宫各画两条对角线，与网格合成「米」字；
        · 炮位 / 兵位画 L 形定位折角。
        """
        river_top = self.origin_y + 4 * self.cell
        river_bottom = self.origin_y + 5 * self.cell

        for r in range(rows):
            y = self.origin_y + r * self.cell
            color = theme.INK_SOFT if r in (0, rows - 1) else theme.RULE
            width = 2 if r in (0, rows - 1) else 1
            pygame.draw.line(surface, color, (self.origin_x, y), (max_x, y), width)

        for c in range(cols):
            x = self.origin_x + c * self.cell
            color = theme.INK_SOFT if c in (0, cols - 1) else theme.RULE
            width = 2 if c in (0, cols - 1) else 1
            if c in (0, cols - 1):
                pygame.draw.line(surface, color, (x, self.origin_y),
                                 (x, max_y), width)
            else:
                pygame.draw.line(surface, color, (x, self.origin_y),
                                 (x, river_top), width)
                pygame.draw.line(surface, color, (x, river_bottom),
                                 (x, max_y), width)

        # 九宫米字：col 3..5，上方 row 0..2、下方 row 7..9
        x0 = self.origin_x + 3 * self.cell
        x1 = self.origin_x + 5 * self.cell
        for top in (0, 7):
            y0 = self.origin_y + top * self.cell
            y1 = self.origin_y + (top + 2) * self.cell
            pygame.draw.line(surface, theme.RULE, (x0, y0), (x1, y1), 1)
            pygame.draw.line(surface, theme.RULE, (x1, y0), (x0, y1), 1)

        self._draw_chess_position_marks(surface)

        mid_y = self.origin_y + 4.5 * self.cell
        label = assets.mixed(theme.S(20), "楚 河        汉 界", theme.INK_SOFT)
        surface.blit(label, label.get_rect(
            center=((self.origin_x + max_x) / 2, mid_y)))

    def _draw_chess_position_marks(self, surface) -> None:
        """
        炮位 / 兵位的标准 L 形标识（GB/T 棋具技术要求 3.7 / 3.8）：
        交叉点四角各画一个独立的小直角，直角顶点靠近交叉点、两臂向外张开，
        四个角互不相连，不是围成一圈的方框；落在边线上的点只画内侧两角。
        """
        marks = [(2, 1), (2, 7), (7, 1), (7, 7)]
        marks += [(3, c) for c in (0, 2, 4, 6, 8)]
        marks += [(6, c) for c in (0, 2, 4, 6, 8)]
        # 比例按标准棋盘示意图：拐角距交叉点约 0.25 格，臂长约 0.13 格
        gap = max(theme.S(7), int(self.cell * 0.25))
        arm = max(theme.S(5), int(self.cell * 0.13))
        left_limit = self.origin_x
        right_limit = self.origin_x + (self.board.cols - 1) * self.cell

        width = max(1, theme.S(1))
        for row, col in marks:
            x, y = self.cell_center(row, col)
            x, y = int(x), int(y)
            for sx in (-1, 1):
                outer_x = x + sx * (gap + arm)
                if outer_x < left_limit or outer_x > right_limit:
                    continue          # 边线处的兵站只保留内侧两角
                for sy in (-1, 1):
                    corner_x = x + sx * gap
                    corner_y = y + sy * gap
                    outer_y = y + sy * (gap + arm)
                    pygame.draw.line(surface, theme.RULE,
                                     (corner_x, corner_y),
                                     (outer_x, corner_y), width)
                    pygame.draw.line(surface, theme.RULE,
                                     (corner_x, corner_y),
                                     (corner_x, outer_y), width)

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
        if self._is_chess:
            return
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
        """人类回合：在合法落点上点一个淡墨小点，不抢棋子注意力。"""
        r = max(theme.S(2), int(self.cell * 0.07))
        for move in self.board.get_legal_moves():
            if self._is_chess:
                from core.chess.board import decode_sq
                row, col = decode_sq(move[1])
            else:
                row, col = move
            x, y = self.cell_center(row, col)
            pygame.draw.circle(surface, theme.INK_FAINT, (int(x), int(y)), r)

    def _draw_all_stones(self, surface: pygame.Surface) -> None:
        rows, cols = self._grid_shape()
        for r in range(rows):
            for c in range(cols):
                piece = self.board.board[r][c]
                if piece == EMPTY:
                    continue
                if self._is_chess:
                    self._draw_chess_piece(surface, r, c, piece)
                else:
                    self._draw_stone(surface, r, c, piece)

    def _draw_chess_piece(self, surface, row: int, col: int, piece: int) -> None:
        """象棋：圆形棋子 + 汉字，红方朱砂、黑方墨色。"""
        from core.chess.board import piece_side
        x, y = self.cell_center(row, col)
        cx, cy = int(x), int(y)
        radius = int(self.cell * 0.42)
        color = theme.CINNABAR if piece_side(piece) == BLACK else theme.INK
        pygame.draw.circle(surface, theme.STONE_SHADOW,
                           (cx + theme.S(2), cy + theme.S(2)), radius)
        pygame.draw.circle(surface, theme.PAPER, (cx, cy), radius)
        pygame.draw.circle(surface, color, (cx, cy), radius,
                           max(2, int(self.cell * 0.06)))
        name = self.board.piece_name_at(row, col)
        glyph = assets.mixed(int(self.cell * 0.46), name, color)
        surface.blit(glyph, glyph.get_rect(center=(cx, cy)))

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

    def _draw_chess_move_path(self, surface: pygame.Surface) -> None:
        """标注本手起点与走子轨迹（画在棋子之下）；落点括号仍由 _draw_last_move 画。"""
        if self.board.last_move is None:
            return
        from core.chess.board import decode_sq
        src, dst = self.board.last_move
        r0, c0 = decode_sq(src)
        r1, c1 = decode_sq(dst)
        x0, y0 = self.cell_center(r0, c0)
        x1, y1 = self.cell_center(r1, c1)
        width = max(1, theme.S(1))
        pygame.draw.line(surface, theme.RULE, (x0, y0), (x1, y1), width)
        side = int(self.cell * 0.58)
        box = pygame.Rect(int(x0 - side / 2), int(y0 - side / 2), side, side)
        pygame.draw.rect(surface, theme.INK_SOFT, box, width)

    def _draw_last_move(self, surface: pygame.Surface) -> None:
        """最后一手用朱砂四角括号定位；象棋额外在起点补一个朱砂小点。"""
        if self.board.last_move is None:
            return
        if self._is_chess:
            from core.chess.board import decode_sq
            r, c = decode_sq(self.board.last_move[1])
            r0, c0 = decode_sq(self.board.last_move[0])
            x0, y0 = self.cell_center(r0, c0)
            pygame.draw.circle(surface, theme.CINNABAR,
                               (int(x0), int(y0)),
                               max(3, int(self.cell * 0.09)))
        else:
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
        if self._is_chess:
            return  # 象棋候选是起止点编码，不按坐标画圆点
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
