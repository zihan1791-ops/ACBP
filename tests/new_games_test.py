# -*- coding: utf-8 -*-
"""
围棋 / 中国象棋 + 七类通用算法 + 加速层回归测试。

覆盖：规则层关键约束、四棋种 × 七类算法合法步、Edax 在新棋种上的委托、
棋谱落子方记录、批量评估后端与可选 GPU 探测、UI 两段式点击与手动终局。

运行方式（项目根目录下）：
    python tests/new_games_test.py
全部通过时末尾输出 "NEW GAMES TESTS PASSED"。
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from ai.accel import backend_name, batch_scores, gpu_available
from ai.factory import create_ai
from config.args import load_config
from core import BOARD_CLASSES
from core.chess.board import ChessBoard, decode_sq, encode_sq
from core.go.board import GoBoard
from game.modes import create_game
from ui.game_scene import GameScene

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
    cfg = load_config([
        "--mcts-iterations", "30", "--mcts-time", "0.4",
        "--ab-depth", "2", "--ab-time", "0.4",
        "--evo-population", "6", "--evo-generations", "3",
        "--evo-horizon", "3", "--evo-time", "0.8", "--seed", "9",
    ])
    algos = ["mcts", "alphabeta", "random", "iga", "de", "pso", "abc"]

    print("== 规则层 ==")
    chess = ChessBoard(10)
    check("象棋 10 行 9 列、双方各 16 子",
          (chess.rows, chess.cols) == (10, 9) and chess.count_pieces() == (16, 16))
    legal = chess.get_legal_moves()
    check("象棋开局红方 44 步", len(legal) == 44)
    check("炮二平五合法", (encode_sq(7, 1), encode_sq(7, 4)) in legal)
    check("车被己方兵阻挡不可越子",
          (encode_sq(9, 0), encode_sq(4, 0)) not in legal)
    check("走法编码可逆", decode_sq(encode_sq(9, 8)) == (9, 8))
    clone = chess.copy()
    clone.board[0][0] = 0
    check("象棋 copy 与原盘隔离", chess.board[0][0] != 0)

    go = GoBoard(9)
    check("围棋空盘 81 个合法点", len(go.get_legal_moves()) == 81)
    go2 = GoBoard(19)
    check("围棋支持 19 路", go2.size == 19 and len(go2.get_legal_moves()) == 361)

    print("== 七类算法 × 四棋种 ==")
    for kind, size in (("gomoku", 9), ("othello", 8), ("go", 9), ("chess", 10)):
        for algo in algos:
            board = BOARD_CLASSES[kind](size)
            try:
                move = create_ai(algo, board.current_player, cfg).select_move(board)
                check("%s / %s 返回合法步" % (kind, algo),
                      move in board.get_legal_moves())
            except Exception as exc:
                check("%s / %s 无异常 (%s)" % (kind, algo, type(exc).__name__), False)

    for kind in ("go", "chess"):
        board = BOARD_CLASSES[kind](9 if kind == "go" else 10)
        move = create_ai("edax", board.current_player, cfg).select_move(board)
        check("Edax 在 %s 委托通用算法且合法" % kind,
              move in board.get_legal_moves())

    print("== 棋谱与控制器 ==")
    ctrl = create_game("chess", "human_vs_human", None, None, cfg)
    ok = ctrl.handle_human_move((encode_sq(6, 2), encode_sq(5, 2)))
    check("象棋控制器接受编码走法", ok and ctrl.board.move_count == 1)
    check("棋谱落子方记录为阵营值", ctrl.moves and ctrl.moves[0]["player"] == 1)

    print("== 加速层 ==")
    check("后端标识合法", backend_name() in ("cuda", "numpy", "cpu"))
    boards = [BOARD_CLASSES["gomoku"](9) for _ in range(4)]
    scores = batch_scores(boards, 1)
    check("批量评估返回等长结果",
          scores is not None and len(scores) == 4)
    check("GPU 探测不抛异常", isinstance(gpu_available(), bool))
    check("后端未装 torch 时自动回退",
          gpu_available() or backend_name() == "numpy")

    print("== UI 交互 ==")
    from ui.app import App
    app = App(cfg)
    app.scene.draw(app.screen)
    check("主菜单含四个棋种", set(["gomoku", "othello", "go", "chess"])
          .issubset(set(app.scene.GAME_LABELS)))

    chess_ctrl = create_game("chess", "human_vs_human", None, None, cfg)
    scene = GameScene(chess_ctrl, lambda: None)
    scene._handle_chess_click((6, 2))
    scene._handle_chess_click((5, 2))
    check("象棋两段式点击完成落子", chess_ctrl.board.move_count == 1)

    go_ctrl = create_game("go", "human_vs_human", None, None, cfg)
    go_scene = GameScene(go_ctrl, lambda: None)
    check("围棋提供结束对局按钮",
          any(b.text == "结束对局" for b in go_scene.buttons))
    for kind in ("gomoku", "othello", "go", "chess"):
        c = create_game(kind, "human_vs_human", None, None, cfg)
        sc = GameScene(c, lambda: None)
        sc.update()
        sc.draw(app.screen)
    check("四棋种棋盘均可渲染", True)
    pygame.quit()

    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("NEW GAMES TESTS PASSED")


if __name__ == "__main__":
    main()
