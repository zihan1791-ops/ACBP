# -*- coding: utf-8 -*-
"""
路径解析工具。

统一约定：settings.py 中出现的相对路径（如棋谱目录 records）一律相对于
「项目根目录」解析，保证无论从哪个工作目录启动 start.py 都不会找错位置。
"""

import os

# 项目根目录 = 本文件所在目录（utils/）的上级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_path(path: str) -> str:
    """把相对路径解析为项目根下的绝对路径；绝对路径原样返回。"""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)
