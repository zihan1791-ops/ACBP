# -*- coding: utf-8 -*-
"""
大模型 API Key 持久化读写。

约定：
- Key 以 JSON 明文保存在项目 config/llm_keys.json（仅在本地使用）；
- 支持按「模型名」分别保存多家大模型的 Key，方便后续接入其它厂商；
- 游戏中通过「主菜单 → 大模型设置」输入 / 修改 / 清除，对局时自动读取，
  无需每次启动重复输入。

注意：Key 属于敏感信息，本文件仅用于本地便利保存；请勿把 llm_keys.json
提交到公共仓库或分享给他人。
"""

import json
import os
from typing import Dict, Optional

from utils.paths import PROJECT_ROOT

# Key 存储文件（相对项目根目录）
KEY_FILE = os.path.join(PROJECT_ROOT, "config", "llm_keys.json")


def _load_all() -> Dict[str, str]:
    """读取全部已保存的模型 → Key 映射；文件缺失或损坏时返回空字典。"""
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError):
        pass
    return {}


def load_api_key(model: Optional[str] = None) -> str:
    """
    读取指定模型的 API Key；model 为 None 时返回第一个已保存的 Key。

    返回：
        Key 字符串；未配置时返回空字符串。
    """
    keys = _load_all()
    if not keys:
        return ""
    if model is not None and model in keys:
        return keys[model]
    return next(iter(keys.values()), "")


def save_api_key(api_key: str, model: Optional[str] = None) -> None:
    """
    保存指定模型的 API Key（明文写入本地文件）。

    参数：
        api_key: DeepSeek 等平台的 API Key 字符串；
        model:   关联的模型名（默认 'deepseek-flash'），便于多模型分别保存。
    """
    model = model or "deepseek-flash"
    keys = _load_all()
    keys[model] = api_key.strip()
    # keys[model] = "sk-13f1d729c57e47868419d466f4d186ca"

    try:
        os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 保存失败不阻塞对局，下次可重试


def clear_api_key(model: Optional[str] = None) -> bool:
    """清除指定模型（默认第一个）的 Key；返回是否真的清除了内容。"""
    keys = _load_all()
    if not keys:
        return False
    if model is not None:
        removed = keys.pop(model, None)
    else:
        removed = keys.pop(next(iter(keys)), None)
    if removed is None:
        return False
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def has_api_key(model: Optional[str] = None) -> bool:
    """判断是否已配置可用的 API Key。"""
    return bool(load_api_key(model))
