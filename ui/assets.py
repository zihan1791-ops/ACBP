# -*- coding: utf-8 -*-
"""
资源管理：中文字体加载、字体缓存与通用文本渲染辅助。

pygame 默认字体不支持中文，这里按操作系统常见中文字体名称依次匹配；
全部匹配失败时退回默认字体，避免程序崩溃（可能出现中文方框，属环境缺失提示）。
"""

import pygame

# 字体缓存：字号 → pygame.font.Font，避免反复创建字体对象
_font_cache: dict[int, pygame.font.Font] = {}

# 优先尝试的中文字体名称（按系统常见度排序）
_CJK_FONT_NAMES = [
    "Microsoft YaHei",   # Windows 雅黑
    "SimHei",            # Windows 黑体
    "Noto Sans CJK SC",  # Linux / 部分发行版
    "PingFang SC",       # macOS 苹方
    "Arial Unicode MS",
]


def get_font(size: int) -> pygame.font.Font:
    """
    按字号获取已缓存字体；首次创建时依次尝试中文字体。

    参数：
        size: 字号（像素）。
    """
    if size in _font_cache:
        return _font_cache[size]

    font = None
    for name in _CJK_FONT_NAMES:
        path = pygame.font.match_font(name)
        if path:
            font = pygame.font.Font(path, size)
            break
    if font is None:
        # 全部中文字体匹配失败，退回 pygame 默认字体
        font = pygame.font.Font(None, size)

    _font_cache[size] = font
    return font


def render_text(text: str, size: int, color, bold: bool = False) -> pygame.Surface:
    """
    一次性渲染文本为 Surface，便于在场景中直接 blit。

    参数：
        text:  文本内容；
        size:  字号；
        color: 文字颜色 RGB；
        bold:  是否加粗。
    """
    font = get_font(size)
    return font.render(text, True, color)
