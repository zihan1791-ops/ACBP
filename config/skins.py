# -*- coding: utf-8 -*-
"""
棋子外观（皮肤）注册表。

本模块只维护「有哪些外观、默认用哪一个、如何把外部输入归一化」这类
与渲染无关的纯数据规则；图片加载、圆形裁切与缓存放在 ui/piece_skins.py。

皮肤标识：
    classic —— 经典纯色棋子（不带人物头像）
    ember   —— 橙发头像
    azure   —— 蓝发头像
    violet  —— 紫发头像

旧棋谱没有 skin 字段时统一回落到 classic，保证回放仍是当年的纯色棋子，
而不是突然换成新默认头像。
"""

from typing import Dict, Optional

# 菜单展示顺序：经典在前，三种人物头像其后
SKIN_ORDER = ("classic", "ember", "azure", "violet")
SKIN_IDS = SKIN_ORDER

SKIN_LABELS: Dict[str, str] = {
    "classic": "经典",
    "ember": "橙发",
    "azure": "蓝发",
    "violet": "紫发",
}

# 新对局默认：黑方橙发、白方蓝发；玩家可在主菜单里分别更换
DEFAULT_SKINS: Dict[int, str] = {1: "ember", 2: "azure"}

# 棋谱缺少 skin 字段时使用的历史外观
LEGACY_SKIN = "classic"


def is_valid(skin: Optional[str]) -> bool:
    """判断皮肤标识是否在注册表中。"""
    return isinstance(skin, str) and skin in SKIN_LABELS


def normalize(skin: Optional[str], player_id: int) -> str:
    """
    把任意输入归一化为合法皮肤标识。

    非法值或 None 时按玩家编号取默认外观；player_id 也非法时退回经典。
    """
    if is_valid(skin):
        return skin
    return DEFAULT_SKINS.get(player_id, LEGACY_SKIN)


def label(skin: Optional[str]) -> str:
    """返回皮肤的中文标签；未知标识按经典处理。"""
    if is_valid(skin):
        return SKIN_LABELS[skin]
    return SKIN_LABELS[LEGACY_SKIN]


def from_config(config) -> Dict[int, str]:
    """从运行配置读取双方默认皮肤（cfg.p1_skin / cfg.p2_skin）。"""
    return {
        1: normalize(getattr(config, "p1_skin", None), 1),
        2: normalize(getattr(config, "p2_skin", None), 2),
    }


def from_record(record: Optional[dict]) -> Dict[int, str]:
    """
    从棋谱 JSON 还原双方外观。

    players.black.skin / players.white.skin 是写入字段；旧棋谱没有该字段，
    对应一方回落到 classic。缺失或非法值不会中断回放。
    """
    players = (record or {}).get("players") or {}
    result: Dict[int, str] = {}
    for key, player_id in (("black", 1), ("white", 2)):
        role = players.get(key) or {}
        skin = role.get("skin")
        result[player_id] = skin if is_valid(skin) else LEGACY_SKIN
    return result
