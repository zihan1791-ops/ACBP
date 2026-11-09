# -*- coding: utf-8 -*-
"""
Edax 黑白棋外部引擎适配层（可选组件，零 pip 依赖）。

引擎本体（Windows 可执行文件 + data/eval.dat）位于 <项目根>/vendor/edax，
也可用环境变量 ACBP_EDAX_DIR 指向其它目录。文件缺失时该算法在菜单里直接
隐藏，不 import 第三方模块、不启动进程、不安装任何东西，项目其余部分无感。

全部配置均为可选环境变量：
    ACBP_EDAX_DIR    引擎目录（默认 <项目根>/vendor/edax）
    ACBP_EDAX_EXE    可执行文件名（默认 wEdax-x86-64.exe）
    ACBP_EDAX_LEVEL  搜索深度，默认 18
    ACBP_EDAX_TIME   子进程硬超时秒数，默认 8.0
"""

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _ROOT / "vendor" / "edax"
_DEFAULT_EXE = "wEdax-x86-64.exe"


def engine_dir() -> Path:
    raw = os.environ.get("ACBP_EDAX_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_DIR


def exe_path() -> Path:
    name = os.environ.get("ACBP_EDAX_EXE", "").strip() or _DEFAULT_EXE
    return engine_dir() / name


def eval_path() -> Path:
    return engine_dir() / "data" / "eval.dat"


def is_available() -> bool:
    """只做文件存在性检查：不装包、不启动进程、不读权重内容。"""
    try:
        return exe_path().is_file() and eval_path().is_file()
    except OSError:
        return False


def level() -> int:
    try:
        return max(1, min(60, int(os.environ.get("ACBP_EDAX_LEVEL", "18"))))
    except ValueError:
        return 18


def time_limit() -> float:
    try:
        return max(0.5, min(60.0, float(os.environ.get("ACBP_EDAX_TIME", "8.0"))))
    except ValueError:
        return 8.0


__all__ = ["engine_dir", "exe_path", "eval_path", "is_available",
           "level", "time_limit"]
