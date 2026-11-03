# -*- coding: utf-8 -*-
"""
统一日志模块。

根据 config.settings 中的 SHOW_LOG / DEBUG 控制输出级别：
- SHOW_LOG = True  输出常规对局信息；
- DEBUG   = True  额外输出 AI 搜索细节；
两者均为 False 时静默。
"""

# 日志开关状态（由 init_logger 在程序启动时统一写入）
_show_log = True
_debug = False


def init_logger(show_log: bool, debug: bool) -> None:
    """
    初始化日志开关。

    参数：
        show_log: 是否输出常规信息日志；
        debug:    是否输出调试级别日志。
    """
    global _show_log, _debug
    _show_log = bool(show_log)
    _debug = bool(debug)


def log_info(message: str) -> None:
    """输出常规对局信息（AI 落子、回合切换、胜负提示等）。"""
    if _show_log:
        print(f"[INFO] {message}")


def log_debug(message: str) -> None:
    """输出调试细节（仅 DEBUG 开启时打印）。"""
    if _debug:
        print(f"[DEBUG] {message}")


def log_warn(message: str) -> None:
    """输出警告信息（参数异常、非法操作被拦截等），始终打印以便排查问题。"""
    print(f"[WARN] {message}")
