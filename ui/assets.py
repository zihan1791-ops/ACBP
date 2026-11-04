# -*- coding: utf-8 -*-
"""
字体资源层：三套配对字体 + 排版原语（纯前端）。

展示字  华文宋体 / 思源宋体 —— 衬线、编辑感，字距收紧
正文字  等线 / 思源黑体     —— 内敛，承担界面标签
数据字  Cascadia Mono       —— 等宽数字，用于棋步坐标、耗时、胜率

优先按字体文件探测（可控），再退回 pygame 的字体名匹配，最后退回默认字体，
保证任意环境都能启动。所有字体按 (类别, 字号, 粗体) 缓存，避免高频重绘时
反复创建 Font 对象——AI 思考回调里每帧都会重绘，这一点很关键。
"""

import os

import pygame

from . import theme

# 字体文件候选（相对各平台字体目录）；按优先级排列
_FILES = {
    "display": ["STSONG.TTF", "STZHONGS.TTF", "NotoSerifSC-VF.ttf",
                "simsun.ttc", "Songti.ttc", "NotoSerifCJKsc-Regular.otf"],
    "body":    ["Deng.ttf", "Dengb.ttf", "msyh.ttc", "NotoSansSC-VF.ttf",
                "PingFang.ttc", "WenQuanYiMicroHei.ttc"],
    "mono":    ["CascadiaMono.ttf", "CascadiaCode.ttf", "consola.ttf",
                "JetBrainsMono-Regular.ttf", "DejaVuSansMono.ttf"],
}
# 字体名兜底（pygame.font.match_font）
_NAMES = {
    "display": ["STSong", "SimSun", "Noto Serif CJK SC", "Songti SC"],
    "body":    ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                "PingFang SC", "Arial Unicode MS"],
    "mono":    ["Cascadia Mono", "Consolas", "DejaVu Sans Mono"],
}

_FONT_ROOTS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "fonts"),
    os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
    "/System/Library/Fonts",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts",
]

_paths: dict = {}
_cache: dict = {}


def _resolve(kind: str):
    """返回该类别可用的字体文件路径或 pygame 字体名，找不到返回 None。"""
    if kind in _paths:
        return _paths[kind]
    path = None
    for root in _FONT_ROOTS:
        for name in _FILES.get(kind, []):
            candidate = os.path.join(root, name)
            if os.path.isfile(candidate):
                path = candidate
                break
        if path:
            break
    if path is None:
        for name in _NAMES.get(kind, []):
            matched = pygame.font.match_font(name)
            if matched:
                path = matched
                break
    _paths[kind] = path
    return path


def font(kind: str, size: int, bold: bool = False) -> pygame.font.Font:
    """按类别取缓存字体；缺字体时退回 pygame 默认字体，绝不崩。"""
    key = (kind, int(size), bool(bold))
    if key not in _cache:
        path = _resolve(kind)
        try:
            f = pygame.font.Font(path, int(size)) if path else pygame.font.Font(None, int(size))
        except Exception:
            f = pygame.font.Font(None, int(size))
        if bold:
            try:
                f.set_bold(True)
            except Exception:
                pass
        _cache[key] = f
    return _cache[key]


def get_font(size: int, kind: str = "body") -> pygame.font.Font:
    """兼容旧调用：按字号取正文字体。"""
    return font(kind, size)


def render_text(text: str, size: int, color, bold: bool = False,
                kind: str = "body") -> pygame.Surface:
    """兼容旧调用的一次性文本渲染。"""
    return font(kind, size, bold).render(str(text), True, color)


def tracked(kind: str, size: int, text: str, color,
            tracking: float = None) -> pygame.Surface:
    """逐字符拼排，实现 CSS letter-spacing 效果（展示字用）。"""
    if tracking is None:
        tracking = theme.TRACKING
    step = size * tracking
    f = font(kind, size)
    glyphs = [f.render(ch, True, color) for ch in text]
    width = sum(g.get_width() for g in glyphs) + step * max(0, len(glyphs) - 1)
    height = max((g.get_height() for g in glyphs), default=size)
    surf = pygame.Surface((max(1, int(width)), int(height)), pygame.SRCALPHA)
    x = 0.0
    for g in glyphs:
        surf.blit(g, (int(x), 0))
        x += g.get_width() + step
    return surf


def vertical(kind: str, size: int, text: str, color,
             gap: int = 6) -> pygame.Surface:
    """竖排文字（中文刊物标题）：一字一行，水平居中。"""
    f = font(kind, size)
    glyphs = [f.render(ch, True, color) for ch in text]
    width = max((g.get_width() for g in glyphs), default=size)
    height = sum(g.get_height() for g in glyphs) + gap * max(0, len(glyphs) - 1)
    surf = pygame.Surface((int(width), int(height)), pygame.SRCALPHA)
    y = 0
    for g in glyphs:
        surf.blit(g, ((int(width) - g.get_width()) // 2, y))
        y += g.get_height() + gap
    return surf


def mixed(size: int, text: str, color, bold: bool = False,
          cjk_kind: str = "body", latin_kind: str = "mono") -> pygame.Surface:
    """
    中英混排：CJK 字符用正文字体、拉丁字符用等宽字体，逐字符拼排。

    pygame 的等宽字体不含中文字形，直接 render 中文会得到方块；这个函数让
    「AI 思考中」「五子棋 / GOMOKU」这类标签既保留等宽数据感，又能正常显示中文。
    """
    f_cjk = font(cjk_kind, size, bold)
    f_lat = font(latin_kind, size, bold)
    glyphs = []
    for ch in str(text):
        f = f_cjk if ord(ch) > 0x2E80 else f_lat
        glyphs.append(f.render(ch, True, color))
    width = sum(g.get_width() for g in glyphs)
    height = max((g.get_height() for g in glyphs), default=size)
    surf = pygame.Surface((max(1, int(width)), int(height)), pygame.SRCALPHA)
    x = 0
    for g in glyphs:
        surf.blit(g, (x, 0))
        x += g.get_width()
    return surf


def text_width(kind: str, size: int, text: str) -> int:
    return font(kind, size).size(str(text))[0]


def font_report() -> None:
    """打印实际命中的字体，便于设计走查时确认没有退化成默认字体。"""
    for kind in ("display", "body", "mono"):
        path = _resolve(kind)
        print("  font %-8s -> %s" % (kind, path or "FALLBACK (default pygame font)"))
