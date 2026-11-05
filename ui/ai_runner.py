# -*- coding: utf-8 -*-
"""
AI 多进程调度层（纯前端新增模块）。

把「搜索选步」从 pygame 主线程挪到一个长驻 worker 进程，主进程只跑事件循环，
从而根治 AI 计算期间界面卡死：窗口可拖动、可关闭，进度照常实时刷新。

设计要点
--------
1. 长驻 worker：进程只创建一次，之后每步只发任务，避免 Windows spawn 的
   每步 100~300ms 启动开销。
2. 只传轻量数据：棋盘快照（实测 300~400 字节）+ 算法名 + 玩家编号 +
   配置字典；进度只传 ThinkState 的字段 dict，不传整张棋盘、不传对象。
3. worker 侧进度限流 80ms，避免 Queue 堆积；主侧 poll 只保留最新一条。
4. 世代编号 gen：悔棋 / 重开会 cancel() 并递增 gen，过期结果直接丢弃。
5. worker 内部只 import 纯 Python 的 core / ai 层，不加载 pygame 或 UI 主题，
   spawn 时不会重复初始化窗口或字体。
6. 任何环节失败都可回退同步模式（由 GameScene 负责），保证游戏仍能继续。

本模块不修改 core / ai / game 的算法逻辑。
"""

from __future__ import annotations

import multiprocessing as mp
import os
import time
from queue import Empty
from types import SimpleNamespace

# ThinkState 中需要跨进程同步的字段（全部为可序列化的基本类型 / tuple / list）
_THINK_FIELDS = (
    "active", "algo", "player", "phase", "done", "total",
    "depth", "max_depth", "elapsed", "best_move", "best_value",
    "top_moves", "note",
)

# worker 侧进度推送最小间隔（秒）
_PROGRESS_INTERVAL = 0.08


def _snapshot(think) -> dict:
    """把 ThinkState 压成轻量 dict，避免 pickle 整个对象。"""
    return {key: getattr(think, key, None) for key in _THINK_FIELDS}


def _worker(task_q, result_q) -> None:
    """
    长驻 worker 进程入口（模块顶层函数，spawn 可 pickle）。

    任务格式：(gen, board_snapshot, algo_name, player_id, config_dict)
    消息格式：("progress", gen, snapshot) / ("done", gen, move, snapshot)
              / ("error", gen, message)
    """
    # 延迟导入：worker 进程只加载纯 Python 的规则 / 算法层
    from ai.factory import create_ai

    while True:
        task = task_q.get()
        if task is None:                     # 显式退出信号
            return
        gen, board, algo, player, cfg_dict = task
        try:
            ai = create_ai(algo, player, SimpleNamespace(**cfg_dict))
            if ai is None:
                result_q.put(("error", gen, "无法创建 AI 实例"))
                continue

            last_emit = 0.0

            def on_progress(think, _q=result_q, _gen=gen):
                nonlocal last_emit
                now = time.monotonic()
                if now - last_emit < _PROGRESS_INTERVAL:
                    return
                last_emit = now
                _q.put(("progress", _gen, _snapshot(think)))

            move = ai.select_move(board, on_progress=on_progress)
            result_q.put(("done", gen, move, _snapshot(ai.think)))
        except Exception as exc:             # 单个任务失败不应拖垮 worker
            result_q.put(("error", gen, "%s: %s" % (type(exc).__name__, exc)))


class AiRunner:
    """长驻 worker 的提交 / 轮询 / 取消接口（主进程侧）。"""

    def __init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._task_q = self._ctx.Queue()
        self._result_q = self._ctx.Queue()
        self._proc = None
        self._started = False
        self.failed = False
        self.busy = False
        self.gen = 0

    def _ensure_started(self) -> bool:
        if self._started:
            # worker 意外退出（被外部终止 / 崩溃）时不能复用旧队列，
            # 否则新进程会永远阻塞在 task_q.get()，表现为 AI 回合卡住。
            if self._proc is not None and self._proc.is_alive():
                return True
            self.cancel(rebuild=True)
        try:
            self._proc = self._ctx.Process(
                target=_worker, args=(self._task_q, self._result_q),
                daemon=True)
            self._proc.start()
            self._started = True
            return True
        except Exception:
            self.failed = True
            return False

    def submit(self, board, algo: str, player: int, cfg_dict: dict) -> bool:
        """提交一步搜索任务；board 应由调用方传入 copy() 后的快照。"""
        if self.failed or not self._ensure_started():
            return False
        self.gen += 1
        try:
            self._task_q.put((self.gen, board, algo, player, cfg_dict))
            self.busy = True
            return True
        except Exception:
            self.failed = True
            return False

    def is_alive(self) -> bool:
        """worker 是否仍在运行：异常退出时由调用方回退同步模式。"""
        return (self._started and self._proc is not None
                and self._proc.is_alive())

    def poll(self):
        """
        非阻塞取消息；队列里积压的进度只保留最新一条，避免界面处理陈旧帧。
        收到 done / error 时自动清除 busy。
        """
        if not self._started:
            return None
        latest = None
        while True:
            try:
                msg = self._result_q.get_nowait()
            except Empty:
                break
            except Exception:
                break
            if msg[0] in ("done", "error"):
                # 终态消息立即返回，绝不能被同批次里稍晚的 progress 覆盖
                self.busy = False
                return msg
            if not self.busy:
                # 任务已结束才姗姗来迟的旧进度，直接丢弃
                continue
            latest = msg
        return latest

    def cancel(self, rebuild: bool = True) -> None:
        """
        悔棋 / 重开 / 场景切换：终止 worker 并递增 gen，使在途结果全部作废。

        terminate() 强杀 worker 后，multiprocessing.Queue 的内部信号量可能
        残留被杀进程的计数，复用同一对队列会让**新 worker 永久阻塞在
        task_q.get()**——这正是「从对局返回主菜单再开一局，轮到 AI 就卡住」
        的原因。因此默认重建一对干净的 Queue，新进程一定拿得到任务。
        """
        self.gen += 1
        self.busy = False
        self._drain(self._result_q)
        self._drain(self._task_q)
        if self._proc is not None:
            try:
                if self._proc.is_alive():
                    self._proc.terminate()
                self._proc.join(timeout=1.0)
            except Exception:
                pass
        self._proc = None
        self._started = False
        if rebuild:
            try:
                self._task_q.close()
                self._result_q.close()
            except Exception:
                pass
            self._task_q = self._ctx.Queue()
            self._result_q = self._ctx.Queue()
            self.failed = False

    @staticmethod
    def _drain(queue) -> None:
        try:
            while True:
                queue.get_nowait()
        except Exception:
            pass

    def shutdown(self) -> None:
        """显式关闭（进程为 daemon，主进程退出时也会自动结束）。"""
        try:
            if self._started:
                self._task_q.put(None)
        except Exception:
            pass
        self.cancel(rebuild=False)
        try:
            self._task_q.close()
            self._result_q.close()
        except Exception:
            pass


# ===========================================================================
# 全局共享的 worker：整个程序只预启动一次，避免每局 / 每步重新 spawn。
# ===========================================================================
_shared_runner = None


def default_mode() -> str:
    """真实窗口默认异步；无头 / 测试默认同步；ACBP_AI_MODE 可强制覆盖。"""
    forced = os.environ.get("ACBP_AI_MODE", "").strip().lower()
    if forced in ("sync", "async"):
        return forced
    return "sync" if os.environ.get("SDL_VIDEODRIVER", "").lower() == "dummy" \
        else "async"


def shared_runner() -> AiRunner:
    global _shared_runner
    if _shared_runner is None:
        _shared_runner = AiRunner()
    return _shared_runner


def warmup() -> bool:
    """幂等预热：把 spawn 的一次性开销放到程序启动 / 场景构造阶段。"""
    return shared_runner()._ensure_started()


def shutdown_shared() -> None:
    global _shared_runner
    if _shared_runner is not None:
        _shared_runner.shutdown()
        _shared_runner = None
