# -*- coding: utf-8 -*-
"""
四类群体优化下棋 AI 的回归测试（无头，不打开 pygame 窗口）。

覆盖：
1. 注册表 / 命令行预算 / 默认值；
2. 四种算法在五子棋与黑白棋上均返回合法步，并正确填充 ThinkState；
3. 强制预检（一手成五）先验；
4. 时间预算「先到即停」；
5. 多进程 worker 的 SimpleNamespace 配置路径；
6. 两种棋的真实交替对局循环（无非法步、无异常）。

运行方式（项目根目录下）：
    python tests/evolution_ai_test.py
全部通过时末尾输出 "EVOLUTION AI TESTS PASSED"。
"""

import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.evolution import (ArtificialBeeColonyAI, DifferentialEvolutionAI,
                          ImprovedGeneticAI, ParticleSwarmAI)
from ai.factory import create_ai
from config import settings as S
from config.args import load_config
from core.base_board import BLACK, WHITE
from core.gomoku.board import GomokuBoard
from core.othello.board import OthelloBoard
from game.modes import create_game

NAMES = {
    "iga": ImprovedGeneticAI,
    "de": DifferentialEvolutionAI,
    "pso": ParticleSwarmAI,
    "abc": ArtificialBeeColonyAI,
}

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


def mid_gomoku() -> GomokuBoard:
    b = GomokuBoard(9)
    for k in range(6):
        b.apply_move((3 + k // 3, 3 + k % 3))
    return b


def main() -> None:
    print("== 注册表与配置 ==")
    check("VALID_AIS 含四个新算法",
          all(n in S.VALID_AIS for n in NAMES))
    cfg = load_config([
        "--p1-ai", "iga", "--p2-ai", "de",
        "--evo-population", "8", "--evo-generations", "6",
        "--evo-horizon", "4", "--evo-time", "1.5", "--seed", "7",
    ])
    check("命令行覆盖群体预算",
          cfg.evo_population == 8 and cfg.evo_generations == 6
          and cfg.evo_horizon == 4 and cfg.evo_time == 1.5)
    defaults = load_config([])
    check("默认群体预算生效",
          defaults.evo_population == S.EVO_POPULATION
          and defaults.evo_time == S.EVO_TIME_LIMIT)
    for name, cls in NAMES.items():
        check("工厂创建 %s" % name,
              isinstance(create_ai(name, BLACK, cfg), cls))

    print("== 合法步与思考状态 ==")
    for board in (mid_gomoku(), OthelloBoard(8)):
        label = type(board).__name__
        for name in NAMES:
            ai = create_ai(name, board.current_player, cfg)
            calls = [0]
            move = ai.select_move(
                board, on_progress=lambda st: calls.__setitem__(0, calls[0] + 1))
            check("%s / %s 返回合法步" % (name, label),
                  move in board.get_legal_moves())
            check("%s / %s 思考状态完整" % (name, label),
                  ai.think.done > 0 and calls[0] > 0
                  and not ai.think.active and ai.think.best_move == move)

    print("== 强制预检先验 ==")
    win = GomokuBoard(9)
    for c in range(1, 5):
        win.board[4][c] = BLACK
    for name in NAMES:
        move = create_ai(name, BLACK, cfg).select_move(win)
        check("%s 一手成五直接取胜" % name, move in [(4, 0), (4, 5)])

    print("== 时间预算 ==")
    tight = load_config([
        "--evo-population", "40", "--evo-generations", "300",
        "--evo-horizon", "8", "--evo-time", "0.08", "--seed", "3",
    ])
    board = mid_gomoku()
    for name in NAMES:
        ai = create_ai(name, BLACK, tight)
        t0 = time.perf_counter()
        move = ai.select_move(board)
        elapsed = time.perf_counter() - t0
        check("%s 超时返回合法步" % name,
              move in board.get_legal_moves())
        check("%s 未跑满代数且耗时受控" % name,
              ai.think.depth < tight.evo_generations and elapsed < 1.0)

    print("== 多进程 worker 配置路径 ==")
    worker_cfg = SimpleNamespace(**cfg.to_dict())
    for name in NAMES:
        ai = create_ai(name, BLACK, worker_cfg)
        check("%s worker 配置可用" % name,
              ai.select_move(mid_gomoku()) is not None)

    print("== 真实对局循环 ==")
    ctrl = create_game("gomoku", "ai_vs_ai", "iga", "de", cfg,
                       board_size=9)
    check("对局工厂接受新算法",
          ctrl.players[BLACK].ai.name == "iga"
          and ctrl.players[WHITE].ai.name == "de")

    for kind, p1, p2 in (("gomoku", "iga", "de"), ("othello", "pso", "abc")):
        b = GomokuBoard(9) if kind == "gomoku" else OthelloBoard(8)
        black = create_ai(p1, BLACK, cfg)
        white = create_ai(p2, WHITE, cfg)
        ok = True
        for _ in range(10):
            if b.game_over:
                break
            ai = black if b.current_player == BLACK else white
            move = ai.select_move(b)
            if move not in b.get_legal_moves() or not b.apply_move(move):
                ok = False
                break
        check("%s %s vs %s 连续对局无非法步" % (kind, p1, p2), ok)

    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("EVOLUTION AI TESTS PASSED")


if __name__ == "__main__":
    main()
