# -*- coding: utf-8 -*-
"""
棋子头像资源：加载、方形裁切、圆形遮罩与尺寸缓存。

图片放在 ui/images/pieces/ 下，按皮肤标识一一对应。资源按需加载：
第一次绘制某个尺寸时才读盘并缩放，之后命中 LRU 缓存；缺图、损坏或
未安装图像解码器时返回 None，由 BoardView 回退到经典纯色棋子。

约定：
    classic 不使用图片，直接由 BoardView 画纯色棋子；
    face() 返回的 Surface 已经是圆形、带透明边缘、边长等于 diameter。
"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional

import pygame

from config.skins import is_valid
from utils.logger import log_warn

# 皮肤标识 → 文件名；classic 不在这里，它走纯色绘制
FACE_FILES: Dict[str, str] = {
    "ember": "ember.png",
    "azure": "azure.png",
    "violet": "violet.png",
}

IMAGE_DIR = Path(__file__).resolve().parent / "images" / "pieces"

# 原图（已裁成正方形）缓存：键为皮肤标识，缺图为 None
_SOURCE_CACHE: Dict[str, Optional[pygame.Surface]] = {}


def image_path(skin: str) -> Path:
    """返回皮肤对应图片的绝对路径；未知皮肤返回目录本身。"""
    filename = FACE_FILES.get(skin)
    return IMAGE_DIR / filename if filename else IMAGE_DIR


def has_image(skin: str) -> bool:
    """皮肤是否注册了图片且文件确实存在。"""
    return skin in FACE_FILES and image_path(skin).is_file()


def _load_source(skin: str) -> Optional[pygame.Surface]:
    """读取图片并居中裁成正方形；失败返回 None（只尝试一次）。"""
    if skin in _SOURCE_CACHE:
        return _SOURCE_CACHE[skin]

    path = image_path(skin)
    if not path.is_file():
        log_warn(f"棋子外观图片缺失：{path}")
        _SOURCE_CACHE[skin] = None
        return None

    try:
        image = pygame.image.load(str(path))
        # convert_alpha 需要已创建显示表面；无头测试里可能还没有
        if pygame.display.get_surface() is not None:
            image = image.convert_alpha()
    except (pygame.error, OSError) as exc:
        log_warn(f"棋子外观图片读取失败：{path}（{exc}）")
        _SOURCE_CACHE[skin] = None
        return None

    width, height = image.get_size()
    side = min(width, height)
    if side <= 0:
        log_warn(f"棋子外观图片尺寸非法：{path}")
        _SOURCE_CACHE[skin] = None
        return None

    left = (width - side) // 2
    top = (height - side) // 2
    square = image.subsurface((left, top, side, side)).copy()
    _SOURCE_CACHE[skin] = square
    return square


@lru_cache(maxsize=48)
def _face_cached(skin: str, diameter: int) -> Optional[pygame.Surface]:
    """按 (皮肤, 直径) 缓存圆形头像；直径由棋盘格距取整得到。"""
    source = _load_source(skin)
    if source is None:
        return None

    # 先放大到 4 倍直径再画圆遮罩，缩小后边缘比直接画圆更平滑
    big = max(diameter * 4, 128)
    scaled = pygame.transform.smoothscale(source, (big, big))
    mask = pygame.Surface((big, big), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255),
                       (big // 2, big // 2), big // 2)
    scaled.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    face = pygame.transform.smoothscale(scaled, (diameter, diameter))
    if pygame.display.get_surface() is not None:
        try:
            face = face.convert_alpha()
        except pygame.error:
            pass
    return face


def face(skin: Optional[str], diameter: int) -> Optional[pygame.Surface]:
    """
    取圆形头像。

    classic、未知皮肤、缺图都返回 None，调用方据此走纯色棋子分支。
    diameter 会被取整并限制为不小于 8 像素，避免生成零尺寸表面。
    """
    if not is_valid(skin) or skin == "classic":
        return None
    return _face_cached(skin, max(8, int(diameter)))


def thumb(skin: Optional[str], size: int) -> Optional[pygame.Surface]:
    """菜单预览用的方形圆形头像，与棋盘上的头像共用缓存。"""
    return face(skin, size)


def preload(skins: Iterable[Optional[str]],
            diameters: Iterable[int] = (36, 48, 56, 72)) -> None:
    """预热若干皮肤在常见棋子直径下的头像，减少首次落子卡顿。"""
    unique = {skin for skin in skins if is_valid(skin)}
    for skin in unique:
        for diameter in diameters:
            face(skin, diameter)


def clear_cache() -> None:
    """清空图片与尺寸缓存（替换素材或测试时使用）。"""
    _SOURCE_CACHE.clear()
    _face_cached.cache_clear()
