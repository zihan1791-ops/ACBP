# -*- coding: utf-8 -*-
"""
外观设置场景（AppearanceScene）—— 主菜单点「外观设置」进入的独立页面。

两栏各 3 张卡片：棋盘皮肤 / 棋子皮肤，互相独立、可自由组合。
每张卡片内嵌缩略预览：棋盘卡用当前棋子皮肤演示，棋子卡用当前棋盘
皮肤演示，因此任意选中态看到的就是实际对局效果。

选择即时写入 user_prefs.json（ui/skins.py 负责），所有场景下一帧即生效；
「恢复默认」回到 paper / classic 纯代码绘制；「返回主菜单」由 App 路由。
"""

from typing import Callable, List

import pygame

from . import theme, motion, assets, atmosphere, skins
from .widgets import Button, blit_reveal, keyboard_nav


class SkinCard:
    """皮肤卡片：矩形点击区 + 缩略预览 + 名称 / 说明 + 选中态。"""

    def __init__(self, rect, kind: str, spec: dict,
                 on_click: Callable[[], None], row_no: int = 1) -> None:
        self.rect = pygame.Rect(rect)
        self.kind = kind                 # "board" / "stone"
        self.spec = spec
        self.enabled = True
        self.on_click = on_click
        self.selected = False
        self.hover = False
        self.focused = False
        self.reveal = 1.0
        self.reveal_delay = 120 + row_no * theme.MOTION["stagger"]

    def handle_event(self, event: pygame.event.Event) -> bool:
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos)):
            self.on_click()
            return True
        return False

    def update(self, mouse_pos: tuple) -> None:
        self.hover = self.rect.collidepoint(mouse_pos)

    def draw(self, surface: pygame.Surface) -> None:
        s = theme.S
        p = max(0.0, min(1.0, self.reveal))
        if p <= 0.0:
            return
        r = self.rect.move(int((1.0 - p) * s(24)), 0)
        fade = lambda c: theme.blend(c, theme.PAPER, 1.0 - p)

        pygame.draw.rect(surface, fade(theme.SURFACE), r,
                         border_radius=theme.RADIUS)
        if self.hover and not self.selected:
            pygame.draw.rect(surface, fade((238, 230, 216)), r,
                             border_radius=theme.RADIUS)
        border = theme.CINNABAR if self.selected else theme.RULE_LIGHT
        pygame.draw.rect(surface, fade(border), r, width=1,
                         border_radius=theme.RADIUS)
        if self.selected:
            pygame.draw.rect(surface, fade(theme.CINNABAR),
                             (r.x, r.y, s(5), r.height))
            pygame.draw.line(surface, fade(theme.CINNABAR),
                             (r.x, r.y), (r.x + s(38), r.y), 3)

        # 左：缩略预览（棋盘款展示整块棋盘，棋子款展示黑白两子）
        box = pygame.Rect(r.x + s(16), r.y + s(16), s(128), s(128))
        pygame.draw.rect(surface, fade(theme.RULE_LIGHT), box.inflate(s(4), s(4)),
                         width=1, border_radius=theme.RADIUS)
        self._draw_preview(surface, box)
        pygame.draw.rect(surface, fade(theme.RULE), box, width=1)

        # 右：名称 / 说明 / 选中标记
        tx = r.x + s(164)
        name = assets.font("body", s(22), True).render(
            self.spec["name"], True,
            fade(theme.CINNABAR if self.selected else theme.INK))
        surface.blit(name, (tx, r.y + s(30)))
        desc = assets.mixed(s(16), self.spec["desc"], fade(theme.INK_SOFT))
        surface.blit(desc, (tx, r.y + s(72)))
        tag = "当前使用" if self.selected else "点击应用"
        tip = assets.mixed(s(15), tag,
                           fade(theme.CINNABAR if self.selected else theme.INK_SOFT))
        surface.blit(tip, (tx, r.y + s(108)))

        if self.focused:
            atmosphere.brackets(surface, r, fade(theme.CINNABAR), 12, 2)

    # ---- 缩略预览 -----------------------------------------------------

    def _draw_preview(self, surface: pygame.Surface,
                      box: pygame.Rect) -> None:
        s = theme.S
        if self.kind == "board":
            board_id = self.spec["id"]
            stone_id = skins.get_stone_skin()
        else:
            board_id = skins.get_board_skin()
            stone_id = self.spec["id"]
        pal = skins.board_palette(board_id)
        sp = skins.stone_palette(stone_id)

        tex = skins.board_texture(box.width, box.height, board_id)
        if tex is not None:
            surface.blit(tex, box.topleft)
        else:
            pygame.draw.rect(surface, pal["bg"], box)

        # 5x5 示意网格
        step = box.width / 6.0
        for i in range(1, 6):
            x = box.x + i * step
            y = box.y + i * step
            pygame.draw.line(surface, pal["grid"], (x, box.y + step * 0.5),
                             (x, box.bottom - step * 0.5), 1)
            pygame.draw.line(surface, pal["grid"], (box.x + step * 0.5, y),
                             (box.right - step * 0.5, y), 1)

        radius = max(4, int(step * 0.40))
        stones = [(2, 2, True), (4, 3, False)]
        if self.kind == "board":
            stones = [(2, 2, True)]        # 棋盘卡只点一子，突出底纹
        for col, row, black in stones:
            cx = int(box.x + col * step)
            cy = int(box.y + row * step)
            pygame.draw.circle(surface, pal["stone_shadow"],
                               (cx + max(1, s(1)), cy + max(1, s(1))), radius)
            stone_tex = skins.stone_texture(black, radius * 2 + 1, stone_id)
            if stone_tex is not None:
                surface.blit(stone_tex, (cx - radius, cy - radius))
            else:
                pygame.draw.circle(surface,
                                   sp["black"] if black else sp["white"],
                                   (cx, cy), radius)
                pygame.draw.circle(surface,
                                   sp["black_rim"] if black else sp["white_rim"],
                                   (cx, cy), radius, 1)


class AppearanceScene:
    """外观设置页：两栏 3+3 卡片 + 恢复默认 + 返回主菜单。"""

    def __init__(self, cfg, on_back: Callable[[], None]) -> None:
        self.cfg = cfg
        self.on_back = on_back
        self.w, self.h = theme.window_size(cfg)
        self.born = motion.now()
        self.kb_index = 0
        self.kb_mode = False
        self.widgets: List = []
        self._build_layout()

    # ===================== 布局 =====================

    def _build_layout(self) -> None:
        s = theme.S
        self.widgets.clear()
        columns = [
            ("board", s(72), skins.board_skins(), skins.set_board_skin),
            ("stone", s(740), skins.stone_skins(), skins.set_stone_skin),
        ]
        for col_i, (kind, x, items, setter) in enumerate(columns):
            for i, spec in enumerate(items):
                sid = spec["id"]
                card = SkinCard(
                    (x, s(160) + i * s(182), s(628), s(160)),
                    kind, spec,
                    on_click=lambda k=kind, v=sid, f=setter: self._select(k, v, f),
                    row_no=col_i * 3 + i + 1)
                self.widgets.append(card)

        reset = Button((s(72), s(780), s(240), s(56)), "恢复默认",
                       on_click=self._reset, font_size=theme.FONT_BODY)
        reset.reveal_delay = 420
        back = Button((s(1128), s(780), s(240), s(56)), "返回主菜单",
                      on_click=self.on_back, accent=True,
                      font_size=theme.FONT_BODY)
        back.reveal_delay = 480
        self.widgets.extend([reset, back])

    def _select(self, kind: str, skin_id: str, setter) -> None:
        setter(skin_id)
        # 贴图按 id + 尺寸缓存，清一次让换肤后的下一帧立即重建
        skins.clear_cache()

    def _reset(self) -> None:
        skins.reset()
        skins.clear_cache()

    # ===================== 事件与更新 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            self.kb_mode = False
        elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_TAB, pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT,
                pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER,
                pygame.K_SPACE):
            self.kb_mode = True
            self.kb_index = keyboard_nav(self.widgets, event, self.kb_index)
            self.kb_index = min(self.kb_index, max(0, len(self.widgets) - 1))
            return
        for widget in self.widgets:
            if widget.handle_event(event):
                return

    def update(self) -> None:
        mouse_pos = pygame.mouse.get_pos()
        board_id, stone_id = skins.get_board_skin(), skins.get_stone_skin()
        self.kb_index = min(self.kb_index, max(0, len(self.widgets) - 1))
        for i, widget in enumerate(self.widgets):
            widget.update(mouse_pos)
            if isinstance(widget, SkinCard):
                widget.selected = widget.spec["id"] == (
                    board_id if widget.kind == "board" else stone_id)
            widget.focused = self.kb_mode and i == self.kb_index

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface) -> None:
        s = theme.S
        surface.blit(atmosphere.paper(self.w, self.h), (0, 0))
        atmosphere.masthead(surface, self.w, "外观设置")

        atmosphere.section_label(surface, "棋盘皮肤", s(72), s(104))
        atmosphere.section_label(surface, "棋子皮肤", s(740), s(104))

        note = assets.mixed(s(16),
                            "两类皮肤可自由组合 · 选择即时生效并保存到本机",
                            theme.INK_SOFT)
        surface.blit(note, (s(72), s(716)))
        current = "当前：%s 棋盘 / %s 棋子" % (
            skins.board_by_id(skins.get_board_skin())["name"],
            skins.stone_by_id(skins.get_stone_skin())["name"])
        summary = assets.mixed(s(17), current, theme.INK)
        blit_reveal(surface, summary, (s(740), s(716)),
                    motion.reveal(self.born, 300, theme.MOTION["base"]), 14)

        for widget in self.widgets:
            widget.reveal = motion.reveal(
                self.born, getattr(widget, "reveal_delay", 0),
                theme.MOTION["base"])
            widget.draw(surface)

        pygame.draw.line(surface, theme.RULE_LIGHT,
                         (s(36), s(856)), (self.w - s(36), s(856)))
        keys = assets.mixed(s(15), "Tab 选择 · Enter 确认 · R 关闭动效",
                            theme.INK_SOFT)
        blit_reveal(surface, keys, (s(36), s(866)),
                    motion.reveal(self.born, 560, theme.MOTION["base"]), 8)
