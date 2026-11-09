# -*- coding: utf-8 -*-
"""
Edax `-solve` 子进程调用：写 OBF → 求解 → 解析主变例首着 → 清理临时文件。

无状态的一次性调用，无需维护长驻引擎；超时由 subprocess 强制终止，
失败一律返回 None，由上层降级，绝不让外部引擎拖垮对局。
"""

import os
import re
import subprocess
import tempfile

from . import engine_dir, eval_path, exe_path, is_available
from .obf import MOVE_RE, board_to_obf, notation_to_rc

_SCORE_RE = re.compile(r"[+-]\d+")


def parse_solve_output(stdout: str):
    """
    数据行形如：
      1|18@73%  +01   0:00.032   978609   D3 f5 F4 g5 D2 c1 G4
    取 PV 首着与 score 列的评估分（近似最终子数差）。
    """
    for line in stdout.splitlines():
        if "|" not in line or line.lstrip().startswith("#"):
            continue
        rhs = line.split("|", 1)[1]
        m = MOVE_RE.search(rhs)
        if m is None:
            continue
        s = _SCORE_RE.search(rhs)
        return notation_to_rc(m.group(0)), (int(s.group(0)) if s else 0)
    return None


def solve(board, depth: int, timeout: float):
    """返回 ((row, col), score)；任何异常返回 None。"""
    if not is_available():
        return None

    directory = engine_dir()
    fd, path = tempfile.mkstemp(prefix="acbp_", suffix=".obf",
                                dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(board_to_obf(board) + "\n")
        cmd = [str(exe_path()), "-solve", path, "-l", str(depth),
               "-eval-file", str(eval_path()), "-book-usage", "off"]
        proc = subprocess.run(
            cmd, cwd=str(directory), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False)
        return parse_solve_output(proc.stdout.decode("utf-8", "replace"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
