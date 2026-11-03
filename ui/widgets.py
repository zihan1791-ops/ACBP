# -*- coding: utf-8 -*-
"""
通用 pygame 控件库：按钮、选项按钮、圆角面板与文本绘制辅助。

主菜单与对局场景复用这些控件，保证按钮样式、圆角、配色完全统一。
"""

import pygame
from typing import Callable, Optional

from . import theme
from .assets import get_font


class Panel:
    """圆角信息面板：统一的浅色底 + 浅棕边框。"""

    def __init__(self, rect) -> None:
        self.rect = pygame.Rect(rect)

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, theme.PANEL, self.rect, border_radius=theme.RADIUS)
        pygame.draw.rect(surface, theme.PANEL_BORDER, self.rect,
                         width=1, border_radius=theme.RADIUS)


class Button:
    """
    普通按钮：支持悬停变色、选中高亮与点击回调。

    属性：
        selected: 选中态（绿色填充白字），用于选项类按钮；
        accent:   主操作按钮（开始 / 重开等），使用强调色填充。
    """

    def __init__(self, rect, text: str, on_click: Optional[Callable] = None,
                 font_size: int = theme.FONT_BODY, selected: bool = False,
                 accent: bool = False) -> None:
        self.rect = pygame.Rect(rect)
        self.text = text
        self.on_click = on_click
        self.font_size = font_size
        self.selected = selected
        self.accent = accent
        self.hover = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        """处理鼠标点击；命中按钮并触发回调时返回 True。"""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                if self.on_click is not None:
                    self.on_click()
                return True
        return False

    def update(self, mouse_pos: tuple[int, int]) -> None:
        """刷新悬停状态。"""
        self.hover = self.rect.collidepoint(mouse_pos)

    def draw(self, surface: pygame.Surface) -> None:
        # 计算填充颜色：选中 > 主按钮 > 悬停 > 普通
        if self.selected:
            fill = theme.ACCENT
        elif self.accent:
            fill = theme.ACCENT_DARK if self.hover else theme.ACCENT
        elif self.hover:
            fill = theme.BUTTON_HOVER
        else:
            fill = theme.BUTTON

        pygame.draw.rect(surface, fill, self.rect, border_radius=theme.RADIUS)
        text_color = theme.TEXT_ON_ACCENT if (self.selected or self.accent) else theme.TEXT

        font = get_font(self.font_size)
        label = font.render(self.text, True, text_color)
        surface.blit(label, label.get_rect(center=self.rect.center))


def draw_text(surface: pygame.Surface, text: str, x: int, y: int,
              size: int = theme.FONT_BODY, color=theme.TEXT,
              bold: bool = False, align: str = "left") -> None:
    """
    在指定位置绘制文本。

    参数：
        align: left 以 (x,y) 为左上角；center 以 (x,y) 为水平中心；right 右对齐。
    """
    font = get_font(size)
    label = font.render(text, True, color)
    if align == "center":
        rect = label.get_rect(center=(x, y))
    elif align == "right":
        rect = label.get_rect(topright=(x, y))
    else:
        rect = label.get_rect(topleft=(x, y))
    surface.blit(label, rect)


class ProgressBar:
    """
    圆角进度条控件：用于可视化 AI 搜索进度。

    参数：
        rect:     控件矩形；
        max_value: 进度上限（0 表示不确定进度，仅显示已工作量）；
        label:    进度条上方的小标题。
    """

    def __init__(self, rect, max_value: float = 0.0, label: str = "") -> None:
        self.rect = pygame.Rect(rect)
        self.max_value = max_value
        self.label = label

    def draw(self, surface: pygame.Surface, value: float) -> None:
        # 底槽
        pygame.draw.rect(surface, theme.BUTTON, self.rect, border_radius=theme.RADIUS)
        # 填充（进度按 0~max 归一化；max<=0 时按未知进度显示 15% 基础条）
        if self.max_value > 0:
            ratio = max(0.0, min(1.0, value / self.max_value))
        else:
            ratio = 0.15 if value > 0 else 0.0
        if ratio > 0:
            fill_rect = pygame.Rect(
                self.rect.x + 2, self.rect.y + 2,
                max(6, int((self.rect.width - 4) * ratio)), self.rect.height - 4)
            pygame.draw.rect(surface, theme.ACCENT, fill_rect, border_radius=theme.RADIUS)
        # 边框
        pygame.draw.rect(surface, theme.PANEL_BORDER, self.rect,
                         width=1, border_radius=theme.RADIUS)
        if self.label:
            draw_text(surface, self.label, self.rect.x + theme.S(8),
                      self.rect.y - theme.S(22),
                      size=theme.FONT_SMALL, color=theme.TEXT_LIGHT)
