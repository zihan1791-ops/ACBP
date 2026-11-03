# -*- coding: utf-8 -*-
"""
高 DPI 显示支持（Windows 高分屏缩放适配）。

问题背景：
    在 2K / 4K 高分屏且系统开启了缩放（如 125% / 150%）时，pygame 窗口
    默认会被 Windows 按位图方式整体放大，点阵字体与线条被插值放大后
    明显发糊。

解决思路：
    1. 进程声明 DPI 感知（SetProcessDpiAwareness）——Windows 不再缩放窗口，
       窗口尺寸按物理像素计算；
    2. 读取系统 DPI 缩放系数（GetDpiForSystem / 96），由 theme 层把字号、
       间距、布局坐标统一放大，让所有内容以物理像素「原生渲染」，保持清晰。

注意：
    enable_dpi_awareness 必须在 pygame.init() / 创建窗口之前调用。
"""

import ctypes
from typing import Optional

_SCALE: Optional[float] = None


def enable_dpi_awareness() -> None:
    """
    声明进程为「每显示器 DPI 感知」，阻止 Windows 对窗口做位图缩放。

    优先使用 Win10 1607+ 的 SetProcessDpiAwareness(2)；旧系统回退到
    SetProcessDPIAware()。重复调用 / 调用失败均静默忽略（不影响后续逻辑）。
    """
    try:
        # PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def dpi_scale() -> float:
    """
    返回系统 DPI 缩放系数（96 DPI = 1.0；150% 缩放 = 1.5）。

    该值在首次调用时读取并缓存；窗口创建后系统缩放一般不会变化，
    因此运行期只需读取一次。
    """
    global _SCALE
    if _SCALE is None:
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            _SCALE = dpi / 96.0
        except Exception:
            _SCALE = 1.0
    return _SCALE
