# -*- coding: utf-8 -*-
"""
通用控件库（纯前端）—— 编辑式纸墨风格的按钮 / 面板 / 进度条 / 排版辅助。

保持既有类名与调用签名不变：
    Panel(rect)                      .rect / .draw(surface)
    Button(rect, text, on_click, font_size, selected, accent, ...)
                                     .rect/.text/.selected/.accent/.hover
                                     .handle_event / .update / .draw
    ProgressBar(rect, max_value, label) .max_value/.label/.draw(surface, value)
    draw_text(surface, text, x, y, size, color, bold, align)
    draw_kv(surface, label, value, x, y, width, size, ...)

视觉纪律：默认态只用发丝线与墨字；悬停用「朱砂下划线从左擦除」；
选中 / 主操作才用唯一强调色实心；键盘焦点用四角括号 + 左侧朱砂竖条。
信息性文字统一用 INK_SOFT（4.90:1），INK_FAINT 只留给装饰线。
"""

from typing import Callable, Optional

import pygame

from . import theme, motion, assets, atmosphere


class Panel:
    """宣纸面板：浅色底 + 发丝边框 + 顶部朱砂短线（不再附加装饰角标）。"""

    def __init__(self, rect) -> None:
        self.rect = pygame.Rect(rect)

    def draw(self, surface: pygame.Surface) -> None:
        s = theme.S
        pygame.draw.rect(surface, theme.SURFACE, self.rect,
                         border_radius=theme.RADIUS)
        pygame.draw.rect(surface, theme.RULE_LIGHT, self.rect,
                         width=1, border_radius=theme.RADIUS)
        pygame.draw.line(surface, theme.CINNABAR,
                         (self.rect.x, self.rect.y),
                         (self.rect.x + s(34), self.rect.y), 3)


class Button:
    """按钮：默认 / 悬停 / 按下 / 选中 / 主操作 / 键盘焦点 / 禁用 七态。"""

    def __init__(self, rect, text: str, on_click: Optional[Callable] = None,
                 font_size: int = theme.FONT_BODY, selected: bool = False,
                 accent: bool = False, kind: str = "body",
                 enabled: bool = True, flat: bool = False,
                 prefix: str = "") -> None:
        self.rect = pygame.Rect(rect)
        self.text = text
        self.on_click = on_click
        self.font_size = font_size
        self.selected = selected
        self.accent = accent
        self.kind = kind
        self.enabled = enabled
        self.flat = flat              # 目录行样式：无边框，仅发丝分隔线
        self.prefix = prefix          # 目录行的等宽编号（数据标识）
        self.hover = False
        self.focused = False
        self.reveal = 1.0
        self._hp = 0.0
        self._last_t = pygame.time.get_ticks()

    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                if self.on_click is not None:
                    self.on_click()
                return True
        return False

    def update(self, mouse_pos: tuple) -> None:
        self.hover = self.enabled and self.rect.collidepoint(mouse_pos)

    def _draw_focus(self, surface, rect, fade) -> None:
        """焦点：四角括号 + 左侧朱砂竖条，大画布上更容易定位。"""
        atmosphere.brackets(surface, rect, fade(theme.CINNABAR), 12, 2)
        pygame.draw.rect(surface, fade(theme.CINNABAR),
                         (rect.x - theme.S(6), rect.y,
                          theme.S(4), rect.height))

    def draw(self, surface: pygame.Surface) -> None:
        s = theme.S
        p = max(0.0, min(1.0, self.reveal))
        if p <= 0.0:
            return
        r = self.rect.move(int((1.0 - p) * s(32)), 0)
        fade = lambda c: theme.blend(c, theme.PAPER, 1.0 - p)

        tick = pygame.time.get_ticks()
        dt = max(0, tick - self._last_t)
        self._last_t = tick
        self._hp = motion.ramp(self._hp, 1.0 if self.hover else 0.0,
                               dt, theme.MOTION["micro"])

        # 目录行：发丝线 + 等宽编号 + 一大号文字
        if self.flat:
            if self.enabled and self._hp > 0.01:
                wash = pygame.Surface(
                    (max(1, int(r.width * self._hp)), r.height), pygame.SRCALPHA)
                wash.fill((*theme.CINNABAR, int(26 * p)))
                surface.blit(wash, r.topleft)
            if self.prefix:
                pre = assets.font("mono", s(14)).render(
                    self.prefix, True, fade(theme.CINNABAR))
                pre.set_alpha(int(255 * p))
                surface.blit(pre, (r.x + s(14), r.y + s(20)))
                pre.set_alpha(255)
            row = assets.mixed(s(17), str(self.text),
                               fade(theme.INK if self.enabled else theme.INK_SOFT))
            row.set_alpha(int(255 * p))
            surface.blit(row, (r.x + s(64), r.y + s(17)))
            row.set_alpha(255)
            pygame.draw.line(surface, fade(theme.RULE_LIGHT),
                             (r.x, r.bottom), (r.right, r.bottom))
            if self.focused and self.enabled:
                self._draw_focus(surface, r, fade)
            return

        filled = self.selected or self.accent
        if not self.enabled:
            bg, fg = theme.SURFACE, theme.INK_SOFT
        elif self.selected:
            bg, fg = theme.CINNABAR, theme.PAPER_ON_RED
        elif self.accent:
            bg = theme.CINNABAR_DK if self._hp > 0.5 else theme.CINNABAR
            fg = theme.PAPER_ON_RED
        else:
            bg, fg = theme.SURFACE, theme.INK

        pygame.draw.rect(surface, fade(bg), r, border_radius=theme.RADIUS)
        pygame.draw.rect(surface, fade(theme.RULE_LIGHT if not filled else bg),
                         r, width=1, border_radius=theme.RADIUS)

        if not filled and self.enabled and self._hp > 0.01:
            width = int(r.width * self._hp)
            pygame.draw.line(surface, fade(theme.CINNABAR),
                             (r.x, r.bottom - 1),
                             (r.x + width, r.bottom - 1), 3)
        if self.selected:
            pygame.draw.rect(surface, fade(theme.CINNABAR_DK),
                             (r.x, r.y, s(4), r.height))

        label_fg = fg if not (self.hover and not filled) else theme.CINNABAR_DK
        label = assets.font(self.kind, self.font_size).render(
            str(self.text), True, label_fg)
        label.set_alpha(int(255 * p))
        surface.blit(label, label.get_rect(center=r.center))
        label.set_alpha(255)

        if self.focused and self.enabled:
            self._draw_focus(surface, r, fade)


def draw_text(surface: pygame.Surface, text: str, x: int, y: int,
              size: int = theme.FONT_BODY, color=theme.TEXT,
              bold: bool = False, align: str = "left",
              kind: str = "body") -> None:
    """在指定位置绘制文本；align 支持 left / center / right。"""
    label = assets.render_text(str(text), size, color, bold, kind)
    if align == "center":
        rect = label.get_rect(center=(x, y))
    elif align == "right":
        rect = label.get_rect(topright=(x, y))
    else:
        rect = label.get_rect(topleft=(x, y))
    surface.blit(label, rect)


def draw_kv(surface: pygame.Surface, label: str, value: str,
            x: int, y: int, width: int = 300, size: int = 17,
            color=None, value_color=None) -> None:
    """
    统一数据行：中文标签左对齐、等宽数值右对齐。
    字号与列宽由参数控制，右栏所有演算数据都走这里，保证对齐一致。
    """
    s = theme.S
    lab = assets.font("body", s(size)).render(label, True,
                                              color or theme.INK_SOFT)
    val = assets.mixed(s(size), str(value), value_color or theme.INK)
    surface.blit(lab, (x, y))
    surface.blit(val, (x + s(width) - val.get_width(), y))


class ProgressBar:
    """细线进度条：朱砂填充 + 标签，用于可视化 AI 搜索进度。"""

    def __init__(self, rect, max_value: float = 0.0, label: str = "") -> None:
        self.rect = pygame.Rect(rect)
        self.max_value = max_value
        self.label = label

    def draw(self, surface: pygame.Surface, value: float) -> None:
        s = theme.S
        if self.label:
            lab = assets.mixed(s(15), self.label, theme.INK_SOFT)
            surface.blit(lab, (self.rect.x, self.rect.y - s(24)))

        pygame.draw.rect(surface, theme.RULE_LIGHT, self.rect,
                         border_radius=s(2))
        ratio = (max(0.0, min(1.0, value / self.max_value))
                 if self.max_value > 0 else (0.15 if value > 0 else 0.0))
        if ratio > 0:
            fill = pygame.Rect(self.rect.x, self.rect.y,
                               max(s(4), int(self.rect.width * ratio)),
                               self.rect.height)
            pygame.draw.rect(surface, theme.CINNABAR, fill,
                             border_radius=s(2))
        pygame.draw.line(surface, theme.RULE,
                         (self.rect.right, self.rect.y - s(4)),
                         (self.rect.right, self.rect.bottom + s(4)))


def blit_reveal(surface: pygame.Surface, glyph: pygame.Surface,
                pos, progress: float, slide: int = 28) -> None:
    """把 0..1 的入场进度应用到一段文字：淡入 + 从左侧滑入。"""
    p = max(0.0, min(1.0, progress))
    if p <= 0.0:
        return
    glyph.set_alpha(int(255 * p))
    dx = int((1.0 - p) * theme.S(slide))
    surface.blit(glyph, (int(pos[0]) + dx, int(pos[1])))
    glyph.set_alpha(255)


def keyboard_nav(buttons, event, current: int,
                 use_arrows: bool = True) -> int:
    """Tab / 方向键循环焦点，Enter / Space 激活；返回新的焦点索引。"""
    enabled = [i for i, b in enumerate(buttons) if b.enabled]
    if not enabled:
        return current
    if current not in enabled:
        current = enabled[0]
    if event.type != pygame.KEYDOWN:
        return current

    k = event.key
    shift_back = k == pygame.K_TAB and bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
    if shift_back or (use_arrows and k in (pygame.K_UP, pygame.K_LEFT)):
        delta = -1
    elif k == pygame.K_TAB or (use_arrows and k in (pygame.K_DOWN, pygame.K_RIGHT)):
        delta = 1
    else:
        delta = 0

    if delta:
        pos = enabled.index(current)
        return enabled[(pos + delta) % len(enabled)]

    if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
        btn = buttons[current]
        if btn.enabled and btn.on_click is not None:
            btn.on_click()
    return current
