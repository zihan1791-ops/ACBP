# -*- coding: utf-8 -*-
"""
AI 多进程调度回归测试（强制 async 模式，无头）。

锁定「AI 大战终局后再开局，AI 一直卡住不算」的根因：
cancel() 终止 worker 后复用同一对 multiprocessing.Queue，Windows spawn
下新 worker 永久阻塞在 task_q.get()；同时 busy=True + is_alive()=True
使原有回退条件不成立，且没有超时兜底。

覆盖：
1. cancel 后重建干净队列；
2. 连续多次 cancel → 重新提交，新 worker 均能返回 done 与合法步；
3. 旧世代终态消息不误清 busy，终态优先于 progress 返回；
4. 终局重开 / 返回菜单二次开局，AI 仍能继续落子；
5. 看门狗超时重试与连续超时回退同步。

运行方式（项目根目录下）：
    python tests/ai_runner_regression_test.py
全部通过时末尾输出 "AI RUNNER REGRESSION PASSED"。
"""

import os
import sys
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["ACBP_AI_MODE"] = "async"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from config.args import load_config
from core.base_board import BLACK
from core.gomoku.board import GomokuBoard
from ui import ai_runner
from ui.app import App

OPTS = {"game_kind": "gomoku", "mode": "ai_vs_ai",
        "p1_ai": "random", "p2_ai": "random", "board_size": 9}

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print("[PASS] %s" % name)
    else:
        failed += 1
        print("[FAIL] %s" % name)


def wait_result(runner, gen, timeout=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        msg = runner.poll()
        if msg and msg[0] in ("done", "error") and msg[1] == gen:
            return msg
        time.sleep(0.01)
    return None


def wait_moves(app, target, timeout=10.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        app.scene.update()
        if len(app.controller.moves) >= target or app.controller.is_over:
            return True
        time.sleep(0.002)
    return False


def main() -> None:
    cfg = load_config(["--game", "gomoku", "--mode", "ai_vs_ai",
                       "--p1-ai", "random", "--p2-ai", "random",
                       "--board-size", "9", "--seed", "7"])

    print("== 队列重建与连续取消 ==")
    runner = ai_runner.AiRunner()
    old_task, old_result = runner._task_q, runner._result_q
    check("预热 worker 成功", runner._ensure_started())
    runner.cancel()
    check("cancel 重建任务队列", runner._task_q is not old_task)
    check("cancel 重建结果队列", runner._result_q is not old_result)
    check("cancel 复位 busy 与 started",
          not runner.busy and not runner._started)

    board = GomokuBoard(9)
    for i in range(3):
        ok = runner.submit(board.copy(), "random", BLACK, cfg.to_dict())
        check("第 %d 次 cancel 后提交成功" % (i + 1), ok)
        msg = wait_result(runner, runner.gen)
        check("第 %d 次新 worker 返回 done" % (i + 1),
              msg is not None and msg[0] == "done")
        check("第 %d 次返回合法步" % (i + 1),
              msg is not None and msg[0] == "done"
              and msg[2] in board.get_legal_moves())
        runner.cancel()
    runner.shutdown()

    print("== poll：世代与终态优先 ==")
    probe = ai_runner.AiRunner()
    probe._started = True          # 仅测 poll 逻辑，不启动真实进程
    probe.busy = True
    probe.gen = 5
    probe._result_q.put(("progress", 5, {"done": 1}))
    probe._result_q.put(("done", 4, (0, 0), {}))
    time.sleep(0.08)
    msg = probe.poll()
    check("终态优先于 progress 返回", msg is not None and msg[0] == "done")
    check("旧世代 done 不误清 busy", probe.busy is True)
    probe.cancel(rebuild=False)

    print("== 集成：终局重开与二次开局 ==")
    app = App(cfg)
    check("开局后 3 手内 AI 正常落子", wait_moves(app, 3))
    first = len(app.controller.moves)

    app.scene._restart()
    check("重开后 AI 继续落子",
          wait_moves(app, 1) and len(app.controller.moves) >= 1)
    check("重开后仍处于异步模式", app.scene._ai_mode == "async")

    app._back_to_menu()
    app._on_menu_start(OPTS)
    check("返回菜单再开局 AI 继续落子",
          wait_moves(app, 1) and len(app.controller.moves) >= 1)
    check("二次开局后仍处于异步模式", app.scene._ai_mode == "async")
    check("首局确实产生过落子", first >= 3)

    print("== 看门狗兜底 ==")
    r = ai_runner.shared_runner()
    r.busy = True
    app.scene._ai_submit_at = time.monotonic() - 100.0
    app.scene.update()
    check("超时触发一次重试",
          app.scene._ai_retry == 1 and app.scene._ai_mode == "async")
    r.busy = True
    app.scene._ai_submit_at = time.monotonic() - 100.0
    app.scene.update()
    check("连续超时回退同步模式", app.scene._ai_mode == "sync")
    before = len(app.controller.moves)
    app.scene.update()
    check("同步模式仍能继续落子", len(app.controller.moves) > before)

    ai_runner.shutdown_shared()
    pygame.quit()

    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("AI RUNNER REGRESSION PASSED")


if __name__ == "__main__":
    main()
