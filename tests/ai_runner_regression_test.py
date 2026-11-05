# -*- coding: utf-8 -*-
"""
异步 AI 调度回归测试（无头，强制 async 模式）
=====================================================================

复现并锁死这个 BUG：从对局「返回主菜单」再开一局后，轮到 AI 时永远不动
（`busy=True`、worker 进程活着、但收不到结果）。

根因：`AiRunner.cancel()` 用 `terminate()` 强杀 worker 后复用同一对
`multiprocessing.Queue`，队列内部信号量残留被杀进程的计数，新 worker
永久阻塞在 `task_q.get()`。修复方式是 cancel 后重建干净的队列，
并在 GameScene 增加超时重试 / 回退同步的看门狗。

覆盖：
1. 连续 4 次「开局 → AI 落子 → 返回主菜单 → 再开局」都不卡住；
2. cancel 后确实重建了任务队列；
3. poll() 的终态消息不会被稍晚的 progress 覆盖；
4. 任务僵死时看门狗能自动重试并让 AI 继续落子。

运行：python tests/ai_runner_regression_test.py
"""

import os
import sys
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["ACBP_AI_MODE"] = "async"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from config.args import load_config
from ui import ai_runner, theme
from ui.app import App

PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError("[FAIL] " + label)
    PASSED += 1
    print("[PASS] " + label)


def wait_ai(app, limit: float = 12.0):
    """模拟主循环，等待 AI 落子；返回 (是否成功, 耗时)。"""
    ctrl, scene = app.controller, app.scene
    t0 = time.time()
    while time.time() - t0 < limit:
        scene.update()
        scene.draw(app.screen)
        pygame.display.flip()
        if not ctrl.current_is_ai:
            return True, time.time() - t0
        time.sleep(0.008)
    return False, time.time() - t0


def main() -> None:
    cfg = load_config(["--mcts-iterations", "150", "--mcts-time", "0.8",
                       "--ab-depth", "2", "--ab-time", "0.5"])
    theme.set_canvas(cfg)
    app = App(cfg)
    opts = {"game_kind": "gomoku", "mode": "human_vs_ai",
            "p1_ai": None, "p2_ai": "mcts", "board_size": 9}

    try:
        check(ai_runner.default_mode() == "async", "测试运行在异步 AI 模式")

        # ---- 1. 连续开局（含返回主菜单触发的 shutdown_ai） --------------
        for i in range(4):
            app._on_menu_start(dict(opts))
            app.controller.handle_human_move((4, 4))   # 人类先手，之后轮到 AI
            ok, elapsed = wait_ai(app)
            check(ok, "第 %d 局 AI 正常落子（%.2fs）" % (i + 1, elapsed))
            check(app.scene._ai_mode == "async",
                  "第 %d 局保持异步模式（未误回退同步）" % (i + 1))
            app._back_to_menu()

        # ---- 2. cancel 重建队列 -----------------------------------------
        runner = ai_runner.shared_runner()
        old_task_q, old_result_q = runner._task_q, runner._result_q
        runner.cancel()
        check(runner._task_q is not old_task_q
              and runner._result_q is not old_result_q,
              "cancel 后重建任务 / 结果队列")
        check(not runner.busy and not runner._started,
              "cancel 后状态复位，等待下次 warmup")

        # ---- 3. 终态消息不被 progress 覆盖 ------------------------------
        ai_runner.warmup()
        gen = runner.gen
        runner._result_q.put(("progress", gen, {"phase": "searching"}))
        runner._result_q.put(("done", gen, (0, 0), {"phase": "done"}))
        msg = None
        t0 = time.time()
        while time.time() - t0 < 1.5:
            msg = runner.poll()
            if msg is not None:
                break
            time.sleep(0.02)
        check(msg is not None and msg[0] == "done",
              "poll 返回 done，未被同批 progress 覆盖")
        check(not runner.busy, "收到 done 后 busy 正确复位")
        runner.cancel()

        # ---- 4. 看门狗：伪造僵死任务，验证自动重试 ----------------------
        app._on_menu_start(dict(opts))
        app.controller.handle_human_move((4, 4))
        scene = app.scene
        runner = scene._runner
        runner.busy = True
        scene._ai_submit_at = time.monotonic() - 999.0   # 伪造超时
        scene.update()
        check(scene._ai_timeouts == 1, "任务僵死时看门狗触发重试")
        check(not runner.busy, "看门狗作废僵死任务并重建队列")
        ok, elapsed = wait_ai(app)
        check(ok, "重试后 AI 仍能正常落子（%.2fs）" % elapsed)
        check(app.scene._ai_timeouts == 0, "成功落子后超时计数清零")

        print("\nAI RUNNER REGRESSION PASSED（%d 项）" % PASSED)
    finally:
        ai_runner.shutdown_shared()
        pygame.quit()


if __name__ == "__main__":
    main()
