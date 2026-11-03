# -*- coding: utf-8 -*-
"""
通用辅助函数：数值裁剪、棋盘边界判断、AI 思考计时器等。
本模块不依赖 pygame 与具体棋种，可供各层复用。
"""

import time


def clamp(value: int, low: int, high: int) -> int:
    """把整数 value 限制在闭区间 [low, high] 内并返回。"""
    return max(low, min(high, value))


def inside_board(row: int, col: int, size: int) -> bool:
    """判断行列坐标 (row, col) 是否位于 size × size 棋盘范围内。"""
    return 0 <= row < size and 0 <= col < size


class MoveTimer:
    """
    AI 思考计时器：用于 MCTS 等搜索过程判断是否达到「时间上限先到即停」。

    用法：
        timer = MoveTimer(limit=2.5)          # 设定 2.5 秒上限
        timer.start()
        while not timer.timeout:
            ...搜索一轮...
        elapsed = timer.elapsed()
    """

    def __init__(self, limit: float) -> None:
        # 时间上限（秒）；limit <= 0 表示不限制时间，仅受迭代次数约束
        self.limit = float(limit) if limit and limit > 0 else 0.0
        # 起始时间戳
        self._start: float = 0.0

    def start(self) -> None:
        """记录当前时刻作为计时起点。"""
        self._start = time.perf_counter()

    @property
    def timeout(self) -> bool:
        """是否已经超过时间上限；未设置上限时恒为 False。"""
        if self.limit <= 0:
            return False
        return (time.perf_counter() - self._start) >= self.limit

    def elapsed(self) -> float:
        """返回自 start() 起经过的秒数。"""
        return time.perf_counter() - self._start
