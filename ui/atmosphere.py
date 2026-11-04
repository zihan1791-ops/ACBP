# -*- coding: utf-8 -*-
"""
氛围层与版面骨架（纯前端）。

纸墨方向的质感不靠纯色平铺：两层极淡径向光晕 + 64 逻辑像素工程网格 +
固定种子的纸纹颗粒 + 左侧装订线，预渲染成一张静态 Surface 缓存。
AI 思考回调会在同线程里高频重绘，缓存能避免每帧重新生成噪点。

刊头只保留品牌、栏目名与版本号；期号、卷号、英文注记等装饰文案已删除。
"""

import random

import pygame

from . import theme
from . import assets

_paper_cache: dict = {}

MASTHEAD_H = 72          # 刊头高度（基准逻辑像素）
GUTTER = 36              # 左右页边距
VERSION = "v0.7.3"       # 保留的数据标识


def _radial(size: int, rgb, max_alpha: int) -> pygame.Surface:
    """用小尺寸同心圆生成径向渐变，避免依赖 numpy 或外部图片。"""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    center, steps = size // 2, 48
    for i in range(steps, 0, -1):
        radius = int(center * i / steps)
        alpha = int(max_alpha * (1 - i / steps) ** 1.5 + 0.4)
        pygame.draw.circle(surf, (*rgb, alpha), (center, center), radius)
    return surf


def paper(w: int, h: int) -> pygame.Surface:
    """返回该尺寸下的静态纸面背景（带缓存）。"""
    key = (w, h)
    if key in _paper_cache:
        return _paper_cache[key]

    base = pygame.Surface((w, h))
    base.fill(theme.PAPER)

    warm = pygame.transform.smoothscale(
        _radial(192, theme.CINNABAR, 12), (int(w * 0.9), int(w * 0.9)))
    base.blit(warm, (-int(w * 0.22), -int(w * 0.30)))
    cool = pygame.transform.smoothscale(
        _radial(192, theme.RULE, 10), (int(w * 0.8), int(w * 0.8)))
    base.blit(cool, (int(w * 0.55), int(h * 0.35)))

    # 工程网格随画布缩放，保持相对密度一致
    grid = pygame.Surface((w, h), pygame.SRCALPHA)
    grid_color = (*theme.RULE, 9)
    step = max(16, theme.S(64))
    for x in range(0, w, step):
        pygame.draw.line(grid, grid_color, (x, 0), (x, h))
    for y in range(0, h, step):
        pygame.draw.line(grid, grid_color, (0, y), (w, y))
    base.blit(grid, (0, 0))

    # 纸纹颗粒：固定种子，保证每次启动一致
    small = pygame.Surface((320, 180), pygame.SRCALPHA)
    rng = random.Random(19)
    for _ in range(12000):
        small.set_at((rng.randrange(320), rng.randrange(180)),
                     (*theme.INK_SOFT, rng.randrange(4, 18)))
    grain = pygame.transform.scale(small, (w, h))
    grain.set_alpha(70)
    base.blit(grain, (0, 0))

    pygame.draw.line(base, theme.RULE_LIGHT, (theme.S(9), 0), (theme.S(9), h))
    pygame.draw.line(base, (233, 220, 200), (theme.S(13), 0), (theme.S(13), h))

    _paper_cache[key] = base
    return base


def masthead(surface: pygame.Surface, w: int, section: str,
             version: str = VERSION) -> int:
    """统一刊头：品牌 + 栏目名 + 版本号，底部双发丝线。返回内容区起始 y。"""
    s = theme.S
    mark = pygame.Surface((s(10), s(10)), pygame.SRCALPHA)
    mark.fill((*theme.CINNABAR, 255))
    surface.blit(mark, (s(GUTTER), s(26)))

    brand = assets.tracked("mono", s(16), "ACBP", theme.INK)
    surface.blit(brand, (s(GUTTER) + s(20), s(21)))

    label = assets.mixed(s(19), section, theme.INK_SOFT)
    surface.blit(label, (s(GUTTER) + s(120), s(19)))

    ver = assets.font("mono", s(14)).render(version, True, theme.INK_SOFT)
    surface.blit(ver, (w - s(GUTTER) - ver.get_width(), s(24)))

    y = s(MASTHEAD_H)
    pygame.draw.line(surface, theme.RULE, (s(GUTTER), y), (w - s(GUTTER), y))
    pygame.draw.line(surface, theme.RULE_LIGHT,
                     (s(GUTTER), y + s(4)), (w - s(GUTTER), y + s(4)))
    return y + s(16)


def hairline(surface: pygame.Surface, start, end,
             color=None, width: int = 1) -> None:
    """发丝分隔线，默认用浅墨。"""
    pygame.draw.line(surface, color or theme.RULE_LIGHT, start, end, width)


def brackets(surface: pygame.Surface, rect, color=None,
             length: int = 12, width: int = 2) -> None:
    """四角直角括号：键盘焦点 / 结构强调。"""
    color = color or theme.CINNABAR
    s = theme.S
    L = s(length)
    l, r, t, b = rect.left, rect.right, rect.top, rect.bottom
    for x, sx in ((l, 1), (r, -1)):
        for y, sy in ((t, 1), (b, -1)):
            pygame.draw.line(surface, color, (x, y), (x + sx * L, y), width)
            pygame.draw.line(surface, color, (x, y), (x, y + sy * L), width)


def column_rule(surface: pygame.Surface, x: int, y1: int, y2: int) -> None:
    """棋谱栏的竖直分栏线。"""
    pygame.draw.line(surface, theme.RULE_LIGHT, (x, y1), (x, y2))
    pygame.draw.line(surface, (226, 215, 195),
                     (x + theme.S(2), y1 + theme.S(8)),
                     (x + theme.S(2), y2 - theme.S(8)))


def section_label(surface: pygame.Surface, text: str,
                  x: int, y: int) -> None:
    """栏目标签：中文小标题 + 一条朱砂短线（不再附加装饰性英文）。"""
    s = theme.S
    zh = assets.font("body", s(19), True).render(text, True, theme.INK)
    surface.blit(zh, (x, y))
    pygame.draw.line(surface, theme.CINNABAR,
                     (x, y + s(30)), (x + s(28), y + s(30)), 2)
