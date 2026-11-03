# -*- coding: utf-8 -*-
"""
文本输入框控件（InputBox）。

用于主菜单「大模型设置」场景中输入 API Key：
- 点击聚焦后键盘输入，支持退格删除、Ctrl+V 粘贴（pygame 剪贴板）；
- secret 模式（API Key 默认开启）用圆点掩码显示，兼顾可输入与隐私；
- 未聚焦时显示浅色占位提示（placeholder）。
"""

import pygame

from . import theme
from .assets import get_font


class InputBox:
    """单行文本输入框。"""

    def __init__(self, rect, placeholder: str = "",
                 secret: bool = False,
                 font_size: int = theme.FONT_BODY) -> None:
        self.rect = pygame.Rect(rect)
        self.placeholder = placeholder
        self.secret = secret          # True：内容以圆点掩码显示
        self.font_size = font_size
        self.text = ""                # 真实内容
        self.active = False           # 是否获得焦点
        self._cursor_on = False
        self._cursor_timer = 0

    # ===================== 事件与更新 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        """处理鼠标聚焦、键盘输入、退格删除与 Ctrl+V 粘贴。"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active = self.rect.collidepoint(event.pos)
            return

        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_v and (event.mod & pygame.KMOD_CTRL):
                pasted = self._paste_text()
                if pasted:
                    self.text += pasted
            elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_TAB):
                pass  # 换行 / 退出交给场景级处理
            elif event.unicode and event.unicode.isprintable():
                self.text += event.unicode

    def update(self, ms: int) -> None:
        """刷新光标闪烁计时。"""
        self._cursor_timer += ms
        if self._cursor_timer >= 500:
            self._cursor_timer = 0
            self._cursor_on = not self._cursor_on

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface) -> None:
        # 底槽与边框（聚焦时使用强调色边框）
        border = theme.ACCENT if self.active else theme.PANEL_BORDER
        pygame.draw.rect(surface, theme.PANEL, self.rect,
                         border_radius=theme.RADIUS)
        pygame.draw.rect(surface, border, self.rect,
                         width=2 if self.active else 1,
                         border_radius=theme.RADIUS)

        # 内容（secret 模式显示圆点；未聚焦且有占位符时显示占位文字）
        if self.text:
            shown = "●" * len(self.text) if self.secret else self.text
            color = theme.TEXT
        else:
            shown = self.placeholder
            color = theme.TEXT_LIGHT

        font = get_font(self.font_size)
        label = font.render(shown, True, color)
        label_rect = label.get_rect(
            midleft=(self.rect.x + theme.S(12), self.rect.centery))
        # 超长内容裁剪（保留尾部）
        max_w = self.rect.width - theme.S(30)
        if label_rect.width > max_w:
            label_rect.width = max_w
            label_rect.right = self.rect.right - theme.S(14)
            clip = surface.get_clip()
            surface.set_clip(self.rect.inflate(-theme.S(6), 0))
            surface.blit(label, label_rect)
            surface.set_clip(clip)
        else:
            surface.blit(label, label_rect)

        # 聚焦光标
        if self.active and self._cursor_on:
            caret_x = label_rect.right + theme.S(2)
            pygame.draw.line(surface, theme.ACCENT_DARK,
                             (caret_x, self.rect.y + theme.S(8)),
                             (caret_x, self.rect.bottom - theme.S(8)), 2)

    # ===================== 内部工具 =====================

    def _paste_text(self) -> str:
        """从系统剪贴板读取文本（失败时返回空串）。"""
        try:
            if pygame.scrap.get_init():
                raw = pygame.scrap.get(pygame.SCRAP_TEXT)
                if raw:
                    return raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            pass
        return ""
