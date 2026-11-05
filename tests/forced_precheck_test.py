# -*- coding: utf-8 -*-
"""
五子棋战术强制预检回归测试（重点：跳三 1101 / 1011）。

背景：群体优化 AI 原本只做「己方成五 / 对手成五」两层预检，对手做出
跳三 X_XX(1011) / XX_X(1101) 时，真正致命的是补中间空位直接连成活四；
旧的 gomoku_defense_points 只返回威胁段的两端，容易漏防。

现在四种进化 AI 与 MCTS / Alpha-Beta 统一复用
ai.candidates.gomoku_forced_move 的四层预检，第四层优先占掉「对手下一手
能成活四」的点。本测试覆盖三种威胁形态、四层优先级与全部六种 AI。

运行方式（项目根目录下）：
    python tests/forced_precheck_test.py
全部通过时末尾输出 "FORCED PRECHECK TESTS PASSED"。
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.candidates import (gomoku_attack_points, gomoku_defense_points,
                           gomoku_forced_move, gomoku_winning_moves)
from ai.factory import create_ai
from config.args import load_config
from core.base_board import BLACK, WHITE
from core.gomoku.board import GomokuBoard

ALGOS = ["iga", "de", "pso", "abc", "mcts", "alphabeta"]
SCATTER = [(0, 0), (0, 8), (8, 0), (8, 8)]

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


def make_board(white_stones, black_stones):
    """按坐标直接摆子构造局面（不经 apply_move，仅用于战术预检）。"""
    b = GomokuBoard(9)
    for r, c in white_stones:
        b.board[r][c] = WHITE
    for r, c in black_stones:
        b.board[r][c] = BLACK
    b.current_player = BLACK
    return b


def main() -> None:
    cfg = load_config([
        "--mcts-iterations", "100", "--mcts-time", "0.5",
        "--ab-depth", "3", "--ab-time", "0.5",
        "--evo-population", "6", "--evo-generations", "3",
        "--evo-time", "1.0", "--seed", "5",
    ])

    print("== 跳三 / 活三威胁：补中间成活四点 ==")
    cases = [
        ("1101 XX_X", [(4, 2), (4, 3), (4, 5)], (4, 4)),
        ("1011 X_XX", [(4, 2), (4, 4), (4, 5)], (4, 3)),
        ("连续活三 XXX", [(4, 3), (4, 4), (4, 5)], None),
    ]
    for label, whites, gap_point in cases:
        board = make_board(whites, SCATTER)
        opp_fours = gomoku_attack_points(board, WHITE)
        expect = ([gap_point] if gap_point else
                  [(4, 2), (4, 6)])
        check("%s 检测到对手成活四点" % label,
              any(p in expect for p in opp_fours))
        if gap_point:
            check("%s 旧堵端点不含补中间点（说明旧逻辑会漏）" % label,
                  gap_point not in gomoku_defense_points(board, BLACK))

        result = gomoku_forced_move(board, BLACK)
        check("%s 公共预检命中成活四点" % label,
              result is not None and result[0] in expect)
        for algo in ALGOS:
            move = create_ai(algo, BLACK, cfg).select_move(
                make_board(whites, SCATTER))
            check("%s %s 强制落在成活四点" % (label, algo), move in expect)

    print("== 四层优先级 ==")
    # 第 1 层：己方有成五点时，不被对手跳三干扰，直接取胜
    win_board = make_board([(6, 2), (6, 3), (6, 5)],
                           [(4, 2), (4, 3), (4, 4), (4, 5)])
    wins = gomoku_winning_moves(win_board, BLACK)
    check("第 1 层 己方成五点存在", len(wins) >= 1)
    for algo in ALGOS:
        move = create_ai(algo, BLACK, cfg).select_move(win_board.copy())
        check("第 1 层 %s 优先进攻" % algo, move in wins)

    # 第 2 层：对手冲四时，即便己方有活三也必须堵五
    block_board = make_board([(4, 2), (4, 3), (4, 4), (4, 5)],
                             [(6, 2), (6, 3), (6, 4)] + SCATTER)
    opp_wins = gomoku_winning_moves(block_board, WHITE)
    check("第 2 层 对手成五点存在", len(opp_wins) >= 1)
    for algo in ALGOS:
        move = create_ai(algo, BLACK, cfg).select_move(block_board.copy())
        check("第 2 层 %s 优先堵五" % algo, move in opp_wins)

    # 第 3 层：己方活三抢先成活四
    attack_board = make_board(SCATTER, [(4, 3), (4, 4), (4, 5)])
    result = gomoku_forced_move(attack_board, BLACK)
    check("第 3 层 己方抢先成活四",
          result is not None and result[0] in [(4, 2), (4, 6)])
    for algo in ALGOS:
        move = create_ai(algo, BLACK, cfg).select_move(attack_board.copy())
        check("第 3 层 %s 抢先成活四" % algo, move in [(4, 2), (4, 6)])

    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("FORCED PRECHECK TESTS PASSED")


if __name__ == "__main__":
    main()
