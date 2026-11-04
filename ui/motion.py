# -*- coding: utf-8 -*-
"""
动效时序与降级开关（纯前端）。

pygame 没有 CSS transition，这里把「一次编排好的入场序列 + 微交互插值 +
prefers-reduced-motion 降级」统一成几个小函数，供所有场景与控件复用。

- reveal(born, delay, dur)：场景入场进度 0..1，错峰 80ms，共用同一条缓动曲线。
- ramp(cur, target, dt)：悬停 / 擦除等微交互插值。
- REDUCED：R 键或环境变量 ACBP_REDUCE_MOTION=1 关闭全部动效，直接给终态。
"""

import os

import pygame

REDUCED = os.environ.get("ACBP_REDUCE_MOTION", "0") == "1"
_T0 = None


def now() -> int:
    """相对进程首次调用的毫秒数；作为全场统一的时间基准。"""
    global _T0
    tick = pygame.time.get_ticks()
    if _T0 is None:
        _T0 = tick
    return tick - _T0


def set_reduced(value: bool) -> None:
    global REDUCED
    REDUCED = bool(value)


def toggle_reduced() -> bool:
    global REDUCED
    REDUCED = not REDUCED
    return REDUCED


def ease_out_cubic(x: float) -> float:
    """对应 cubic-bezier(0.16, 1, 0.3, 1) 的近似，出场统一用它。"""
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def reveal(born: int, delay: int = 0, duration: int = 340) -> float:
    """一次编排好的入场序列中的一组；返回 0..1。"""
    if REDUCED:
        return 1.0
    return ease_out_cubic((now() - born - delay) / max(1, duration))


def ramp(current: float, target: float, dt_ms: float, duration: int = 170) -> float:
    """微交互插值：不依赖帧率地趋近目标值。"""
    if REDUCED:
        return float(target)
    step = min(1.0, max(0.0, dt_ms) / max(1, duration))
    return current + (target - current) * step


def with_alpha(surface: pygame.Surface, progress: float) -> None:
    """把 0..1 的入场进度映射到 Surface 整体透明度（就地修改，调用后需还原）。"""
    surface.set_alpha(int(255 * max(0.0, min(1.0, progress))))
