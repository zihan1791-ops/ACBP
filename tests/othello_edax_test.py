# -*- coding: utf-8 -*-
"""
Edax 黑白棋外部引擎适配层回归测试。

覆盖：OBF 序列化、代数坐标换算、-solve 输出解析、真实引擎返回合法步、
五子棋委托（外部引擎绝不被调用）、引擎缺失时降级、菜单与回放续局的
五子棋隔离。引擎文件缺失时相关用例自动跳过，保证「不装也能跑」。

运行方式（项目根目录下）：
    python tests/othello_edax_test.py
全部通过时末尾输出 "OTHELLO EDAX TESTS PASSED"。
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from ai.factory import create_ai
from ai.othello_ext import is_available
from ai.othello_ext.edax_ai import EdaxAI
from ai.othello_ext.obf import board_to_obf, notation_to_rc
from ai.othello_ext.protocol import parse_solve_output
from config.args import load_config
from core.base_board import BLACK, WHITE
from core.gomoku.board import GomokuBoard
from core.othello.board import OthelloBoard
from ui.app import App
from ui.replay_scene import ReplayScene

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


def main() -> None:
    cfg = load_config([])
    available = is_available()

    print("== 格式与解析 ==")
    start = OthelloBoard(8)
    check("初始局面 OBF 与 Edax start.obf 一致",
          board_to_obf(start) ==
          "---------------------------OX------XO--------------------------- X;")
    check("代数坐标换算 D3 / f5",
          notation_to_rc("D3") == (2, 3) and notation_to_rc("f5") == (4, 5))
    sample = (
        " # | depth|score|       time   |  nodes (N)  |   N/s    | principal variation\n"
        "---+------+-----+--------------+-------------+----------+---------------------\n"
        "  1|18@73%  +01        0:00.032        978609            D3 f5 F4 g5 D2 c1 G4\n"
    )
    check("解析 PV 首着与评估分", parse_solve_output(sample) == ((2, 3), 1))
    check("无 PV 时返回 None", parse_solve_output("no table here") is None)

    print("== 工厂与真实引擎 ==")
    check("工厂创建 EdaxAI", isinstance(create_ai("edax", BLACK, cfg), EdaxAI))
    if available:
        for label, board, player in (
            ("开局黑方", start, BLACK),
        ):
            ai = create_ai("edax", player, cfg)
            move = ai.select_move(board)
            check("%s 返回合法步" % label, move in board.get_legal_moves())
            check("%s 走引擎求解" % label, ai.think.note == "Edax 求解完成")
            check("%s 思考状态完整" % label,
                  ai.think.best_move == move and not ai.think.active)

        mid = OthelloBoard(8)
        rng = random.Random(11)
        for _ in range(21):
            legal = mid.get_legal_moves()
            if not legal or mid.game_over:
                break
            mid.apply_move(rng.choice(legal))
        ai = create_ai("edax", mid.current_player, cfg)
        move = ai.select_move(mid)
        check("中盘 %s 返回合法步" %
              ("黑方" if mid.current_player == BLACK else "白方"),
              move in mid.get_legal_moves())
        check("中盘走引擎求解", ai.think.note == "Edax 求解完成")
    else:
        print("[SKIP] 引擎文件缺失，跳过真实求解用例")

    print("== 五子棋彻底不出现 ==")
    import ai.othello_ext.edax_ai as edax_mod
    original_solve = edax_mod.solve
    calls = []
    edax_mod.solve = lambda *a, **k: calls.append(1) or None
    try:
        gomoku = GomokuBoard(9)
        move = create_ai("edax", BLACK, cfg).select_move(gomoku)
    finally:
        edax_mod.solve = original_solve
    check("五子棋返回合法步（委托 Alpha-Beta）",
          move in gomoku.get_legal_moves())
    check("五子棋不调用外部引擎", not calls)

    app = App(cfg)
    menu = app.scene

    def menu_options():
        return [v for v, _ in menu._player_options("p1")]

    check("五子棋菜单无 edax", "edax" not in menu_options())
    menu._set("game_kind", "othello")
    check("黑白棋菜单 %s edax" % ("有" if available else "无"),
          ("edax" in menu_options()) == available)
    menu._set("p1_ai", "edax")
    menu._set("game_kind", "gomoku")
    check("切回五子棋自动清掉 edax", menu.p1_ai != "edax")
    check("切回后菜单仍无 edax", "edax" not in menu_options())

    rs = ReplayScene(cfg, lambda: None, None)
    rs.record = {"game": "othello"}
    rs.state = "setup"
    rs._build_setup_buttons()
    n_othello = len(rs._indicators)
    rs.record = {"game": "gomoku"}
    rs._build_setup_buttons()
    n_gomoku = len(rs._indicators)
    check("回放续局五子棋无 edax 段",
          n_othello - n_gomoku == (2 if available else 0))
    pygame.quit()

    print("== 引擎缺失时零影响 ==")
    old_dir = os.environ.get("ACBP_EDAX_DIR")
    os.environ["ACBP_EDAX_DIR"] = r"G:\__acbp_no_such_edax_dir__"
    try:
        check("缺失时 is_available 为 False", not is_available())
        fresh = OthelloBoard(8)
        ai = create_ai("edax", BLACK, cfg)
        move = ai.select_move(fresh)
        check("缺失时降级返回合法步", move in fresh.get_legal_moves())
        check("缺失时明确标注降级", ai.think.note == "Edax 未安装")
    finally:
        if old_dir is None:
            del os.environ["ACBP_EDAX_DIR"]
        else:
            os.environ["ACBP_EDAX_DIR"] = old_dir

    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("OTHELLO EDAX TESTS PASSED")


if __name__ == "__main__":
    main()
