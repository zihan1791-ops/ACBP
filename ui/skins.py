# -*- coding: utf-8 -*-
"""
外观皮肤系统（棋盘皮肤 / 棋子皮肤）
=====================================================================

职责：
    1. 维护两套互相独立的皮肤注册表（各 3 套），每套 = 贴图 + 颜色令牌覆盖；
    2. 读写项目根下的用户偏好 user_prefs.json（重启沿用）；
    3. 加载并按尺寸缓存 assets/skins/ 下的 PNG 贴图；
    4. 任何贴图缺失 / 损坏时返回 None，由 BoardView 回退到纯代码绘制。

设计约束：
    - 默认皮肤 paper / classic 不带贴图，继续走原有纯色绘制，
      因此「恢复默认」与改造前逐像素一致，同时是贴图失败时的兜底。
    - 只依赖 pygame + 标准库，不新增第三方依赖，不修改 theme.py 默认常量，
      不影响 core/ 规则层与 BoardView 的坐标换算契约。
    - 运行期只读 PNG，不重新生成纹理；生成脚本见 tools/gen_skins.py。
"""

import json
import os
from typing import Optional

import pygame

from . import theme
from utils.paths import resolve_path, PROJECT_ROOT


SKIN_DIR = resolve_path(os.path.join("assets", "skins"))
PREFS_FILE = resolve_path("user_prefs.json")

DEFAULT_BOARD_SKIN = "paper"
DEFAULT_STONE_SKIN = "classic"


# ===========================================================================
# 1. 皮肤注册表：颜色键名与 BoardView 一一对应
# ===========================================================================
# 棋盘颜色令牌：
#   bg / frame / frame_inner / grid / grid_outer / star / coord / hint /
#   accent / accent_fg / mark_bg / mark_ring / mark_text / stone_shadow
#   stone_shadow：棋子落在棋盘上的投影色，由棋盘底色决定（深色棋盘用暗影）
_BOARD_BASE = {
    "bg":           theme.BOARD_PAPER,
    "frame":        theme.RULE,
    "frame_inner":  theme.RULE_LIGHT,
    "grid":         theme.RULE,
    "grid_outer":   theme.INK_SOFT,
    "star":         theme.STAR_POINT,
    "coord":        theme.INK_SOFT,
    "hint":         theme.INK_FAINT,
    "accent":       theme.CINNABAR,
    "accent_fg":    theme.PAPER_ON_RED,
    "mark_bg":      theme.SURFACE,
    "mark_ring":    theme.INK_SOFT,
    "mark_text":    theme.INK,
    "stone_shadow": theme.STONE_SHADOW,
}

# 棋子颜色令牌：black / white / shadow / black_rim / white_rim
#   shadow 为兼容保留；实际落子投影由棋盘皮肤 stone_shadow 决定（投影落在棋盘上）
_STONE_BASE = {
    "black":     theme.BLACK_STONE,
    "white":     theme.WHITE_STONE,
    "shadow":    theme.STONE_SHADOW,
    "black_rim": theme.STONE_HIGHLIGHT,
    "white_rim": theme.RULE,
}

BOARD_SKINS = (
    {
        "id": "paper", "name": "经典宣纸", "desc": "暖纸白 · 墨线",
        "texture": None, "colors": {},
    },
    {
        "id": "wood", "name": "暖木", "desc": "胡桃木纹 · 烫金线",
        "texture": "board_wood.png",
        "colors": {
            "bg": (168, 126, 82),
            "frame": (96, 64, 40),
            "frame_inner": (206, 166, 116),
            "grid": (72, 48, 30),
            "grid_outer": (58, 38, 24),
            "star": (58, 38, 24),
            "coord": (58, 40, 26),
            "hint": (150, 120, 84),
            "accent": (176, 48, 30),
            "mark_bg": (247, 236, 214),
            "mark_text": (58, 40, 26),
            "stone_shadow": (96, 64, 40),
        },
    },
    {
        "id": "ink", "name": "夜墨", "desc": "深墨石纹 · 银线",
        "texture": "board_ink.png",
        "colors": {
            "bg": (38, 42, 48),
            "frame": (112, 122, 132),
            "frame_inner": (72, 80, 90),
            "grid": (146, 156, 166),
            "grid_outer": (196, 204, 212),
            "star": (196, 204, 212),
            "coord": (188, 198, 208),
            "hint": (96, 106, 118),
            "accent": (232, 102, 74),
            "accent_fg": (38, 30, 28),
            "mark_bg": (238, 240, 242),
            "mark_ring": (110, 120, 130),
            "mark_text": (38, 42, 48),
            "stone_shadow": (12, 14, 18),
        },
    },
)

STONE_SKINS = (
    {
        "id": "classic", "name": "素墨", "desc": "实墨 / 纸白",
        "textures": None, "colors": {},
    },
    {
        "id": "jade", "name": "温玉", "desc": "墨玉 / 米白玉",
        "textures": {"black": "stone_jade_black.png",
                     "white": "stone_jade_white.png"},
        "colors": {
            "black": (26, 44, 40),
            "white": (236, 232, 214),
            "shadow": (150, 138, 116),
            "black_rim": (104, 132, 122),
            "white_rim": (156, 148, 126),
        },
    },
    {
        "id": "agate", "name": "玛瑙", "desc": "黑曜 / 象牙",
        "textures": {"black": "stone_agate_black.png",
                     "white": "stone_agate_white.png"},
        "colors": {
            "black": (24, 20, 28),
            "white": (246, 238, 220),
            "shadow": (150, 138, 116),
            "black_rim": (128, 92, 104),
            "white_rim": (168, 150, 118),
        },
    },
)

_BOARD_BY_ID = {s["id"]: s for s in BOARD_SKINS}
_STONE_BY_ID = {s["id"]: s for s in STONE_SKINS}


def board_skins():
    """返回棋盘皮肤定义元组（只读用）。"""
    return BOARD_SKINS


def stone_skins():
    """返回棋子皮肤定义元组（只读用）。"""
    return STONE_SKINS


def board_by_id(skin_id: str) -> dict:
    return _BOARD_BY_ID.get(skin_id, _BOARD_BY_ID[DEFAULT_BOARD_SKIN])


def stone_by_id(skin_id: str) -> dict:
    return _STONE_BY_ID.get(skin_id, _STONE_BY_ID[DEFAULT_STONE_SKIN])


def board_palette(skin_id: Optional[str] = None) -> dict:
    """棋盘颜色令牌（默认皮肤 = 现有 theme 常量，逐值一致）。"""
    pal = dict(_BOARD_BASE)
    pal.update(board_by_id(skin_id or get_board_skin()).get("colors", {}))
    return pal


def stone_palette(skin_id: Optional[str] = None) -> dict:
    """棋子颜色令牌。"""
    pal = dict(_STONE_BASE)
    pal.update(stone_by_id(skin_id or get_stone_skin()).get("colors", {}))
    return pal


# ===========================================================================
# 2. 用户偏好：项目根 user_prefs.json（本地数据，不入库）
# ===========================================================================
_prefs: Optional[dict] = None
_missing_reported: set = set()


def _valid(kind: str, value) -> bool:
    if not isinstance(value, str):
        return False
    table = _BOARD_BY_ID if kind == "board_skin" else _STONE_BY_ID
    return value in table


def _load_prefs() -> dict:
    global _prefs
    if _prefs is not None:
        return _prefs
    data = {"board_skin": DEFAULT_BOARD_SKIN,
            "stone_skin": DEFAULT_STONE_SKIN}
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as fp:
            raw = json.load(fp)
        if isinstance(raw, dict):
            for key in data:
                if _valid(key, raw.get(key)):
                    data[key] = raw[key]
    except (OSError, ValueError, TypeError):
        pass                      # 文件不存在 / 损坏 → 静默回退默认
    _prefs = data
    return data


def _save_prefs() -> None:
    """写回偏好；磁盘不可写时只影响持久化，不影响本次运行的换肤。"""
    try:
        os.makedirs(PROJECT_ROOT, exist_ok=True)
        with open(PREFS_FILE, "w", encoding="utf-8") as fp:
            json.dump(_load_prefs(), fp, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_board_skin() -> str:
    return _load_prefs()["board_skin"]


def get_stone_skin() -> str:
    return _load_prefs()["stone_skin"]


def set_board_skin(skin_id: str) -> bool:
    if not _valid("board_skin", skin_id):
        return False
    _load_prefs()["board_skin"] = skin_id
    _save_prefs()
    return True


def set_stone_skin(skin_id: str) -> bool:
    if not _valid("stone_skin", skin_id):
        return False
    _load_prefs()["stone_skin"] = skin_id
    _save_prefs()
    return True


def reset() -> None:
    """恢复默认：两套皮肤都回到纯代码绘制的经典款。"""
    prefs = _load_prefs()
    prefs["board_skin"] = DEFAULT_BOARD_SKIN
    prefs["stone_skin"] = DEFAULT_STONE_SKIN
    _save_prefs()


# 供测试注入：清空内存态（不影响已写盘的文件以外的逻辑）
def _forget_prefs() -> None:
    global _prefs
    _prefs = None


# ===========================================================================
# 3. 贴图加载与缩放缓存
# ===========================================================================
_board_cache: dict = {}
_stone_cache: dict = {}


def _convert(surface: pygame.Surface) -> pygame.Surface:
    """display 初始化后才 convert，保证无头 / 生成器环境也能加载。"""
    try:
        if pygame.display.get_init():
            return surface.convert_alpha()
    except pygame.error:
        pass
    return surface


def _load_image(filename: str) -> Optional[pygame.Surface]:
    path = os.path.join(SKIN_DIR, filename)
    if not os.path.isfile(path):
        if filename not in _missing_reported:
            _missing_reported.add(filename)
            print("[ACBP] 皮肤贴图缺失，回退纯色绘制：%s" % filename)
        return None
    try:
        return _convert(pygame.image.load(path))
    except (pygame.error, OSError):
        if filename not in _missing_reported:
            _missing_reported.add(filename)
            print("[ACBP] 皮肤贴图无法读取，回退纯色绘制：%s" % filename)
        return None


def board_texture(width: int, height: int,
                  skin_id: Optional[str] = None) -> Optional[pygame.Surface]:
    """返回缩放到 (width, height) 的棋盘贴图；无贴图皮肤 / 缺图返回 None。"""
    sid = skin_id or get_board_skin()
    key = (sid, int(width), int(height))
    if key in _board_cache:
        return _board_cache[key]
    filename = board_by_id(sid).get("texture")
    result = None
    if filename:
        raw = _load_image(filename)
        if raw is not None and width > 0 and height > 0:
            try:
                result = pygame.transform.smoothscale(raw, (int(width), int(height)))
            except (pygame.error, ValueError):
                result = None
    _board_cache[key] = result
    return result


def stone_texture(black: bool, diameter: int,
                  skin_id: Optional[str] = None) -> Optional[pygame.Surface]:
    """返回缩放后的棋子贴图（带 alpha）；无贴图皮肤 / 缺图返回 None。"""
    sid = skin_id or get_stone_skin()
    key = (sid, bool(black), int(diameter))
    if key in _stone_cache:
        return _stone_cache[key]
    spec = stone_by_id(sid).get("textures")
    result = None
    if spec and diameter > 0:
        raw = _load_image(spec["black" if black else "white"])
        if raw is not None:
            try:
                result = pygame.transform.smoothscale(raw, (int(diameter), int(diameter)))
            except (pygame.error, ValueError):
                result = None
    _stone_cache[key] = result
    return result


def clear_cache() -> None:
    """贴图缓存失效（换肤 / 窗口尺寸变化时按需调用，缓存本身按 id 与尺寸分键）。"""
    _board_cache.clear()
    _stone_cache.clear()
