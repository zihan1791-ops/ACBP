# -*- coding: utf-8 -*-
"""
无头冒烟测试（不打开 pygame 窗口）。

覆盖内容：
1. 五子棋 / 黑白棋 / 围棋规则：合法步、落子、翻转 / 提子、胜负判定；
2. 三类 AI（MCTS / Alpha-Beta / 随机）在开放棋种上均可返回合法走法；
3. 五子棋 AI 强化：强制进攻（成五取胜）、强制防守（堵对手冲四）；
4. MCTS / Alpha-Beta 思考过程状态（ThinkState）在选步后被正确填充；
5. 候选裁剪：五子棋候选点只落在已有棋子邻域；
6. 对局工厂与控制器推进、配置合并与统一预算解析。

运行方式（项目根目录下）：
    python tests/smoke_test.py
全部通过时末尾输出 "ALL TESTS PASSED"。
"""

import os
import sys

# 把项目根目录加入导入路径，保证从 tests 目录运行也能找到各模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 无头模式：禁止 pygame 弹出任何窗口（本测试不实例化界面，属于双保险）
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from config.args import load_config
from config import settings as S
from core.base_board import EMPTY, BLACK, WHITE
from core.gomoku.board import GomokuBoard
from core.othello.board import OthelloBoard
from core.go.board import GoBoard
from ai.factory import create_ai
from ai.candidates import candidate_moves, gomoku_winning_moves
from game.modes import create_game


passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    """记录并打印一条断言结果。"""
    global passed, failed
    if condition:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}")


# ===================== 一、规则测试 =====================

def test_gomoku_rules() -> None:
    print("\n== 五子棋规则 ==")
    board = GomokuBoard(9)

    check("五子棋开局存在合法步", len(board.get_legal_moves()) > 0)

    black_moves = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    white_moves = [(8, 0), (8, 1), (8, 2), (8, 3)]
    for i, bm in enumerate(black_moves):
        check(f"五子棋黑方第 {i + 1} 手可落子", board.apply_move(bm))
        if i < len(white_moves):
            check(f"五子棋白方第 {i + 1} 手可落子", board.apply_move(white_moves[i]))

    check("五子棋五连后对局结束", board.game_over)
    check("五子棋黑方获胜", board.winner == BLACK)
    check("重复落子被拒绝", not board.apply_move((0, 0)))


def test_othello_rules() -> None:
    print("\n== 黑白棋规则 ==")
    board = OthelloBoard(8)
    legal = board.get_legal_moves()
    check("黑白棋开局四个合法步",
          sorted(legal) == sorted([(2, 3), (3, 2), (4, 5), (5, 4)]))

    check("黑白棋黑方合法落子", board.apply_move((2, 3)))
    check("夹吃后白棋被翻转为黑棋", board.board[3][3] == BLACK)

    black, white = board.count_pieces()
    check("黑白棋子数统计正确（黑 4 白 1）", black == 4 and white == 1)


def test_go_rules() -> None:
    print("\n== 围棋规则（代码保留兼容） ==")
    board = GoBoard(9)

    check("围棋黑方落子 (0,1)", board.apply_move((0, 1)))
    check("围棋白方落子 (0,0)", board.apply_move((0, 0)))
    check("围棋黑方落子 (1,0) 完成提子", board.apply_move((1, 0)))
    check("被提白子已清空", board.board[0][0] == EMPTY)
    check("黑方提子计数为 1", board.black_captured == 1)

    suicide = GoBoard(9)
    suicide.apply_move((0, 1))  # 黑
    suicide.apply_move((8, 8))  # 白
    suicide.apply_move((1, 0))  # 黑
    check("围棋自杀落子被拒绝", not suicide.apply_move((0, 0)))
    suicide.end_game_manually()
    check("围棋手动终局标志置位", suicide.game_over)


# ===================== 二、AI 算法测试（开放棋种） =====================

def test_ai_on_active_games() -> None:
    print("\n== AI 算法在开放棋种上选步 ==")
    # 低预算配置，保证测试快速完成（功能等价验证）
    cfg = load_config(["--mcts-iterations", "300", "--ab-depth", "3"])

    boards = {
        "gomoku": GomokuBoard(9),
        "othello": OthelloBoard(8),
    }

    for algo in ["mcts", "alphabeta", "random"]:
        for kind, board in boards.items():
            ai = create_ai(algo, board.current_player, cfg)
            move = ai.select_move(board)
            legal = board.get_legal_moves()
            ok = move is None or move in legal
            check(f"{algo} 选步合法（{kind}）", ok)


def test_gomoku_forced_defense() -> None:
    print("\n== 五子棋 AI 强制防守（挡对手冲四） ==")
    cfg = load_config([])

    # 构造局面：白方（对手）在 (7,3)-(7,6) 已连四子，黑方回合必须堵 (7,2) 或 (7,7)。
    # 注意黑方自己的子需保持分散，避免黑方同时存在制胜点而优先进攻。
    board = GomokuBoard(9)
    for mv, player in [
        ((0, 0), BLACK), ((7, 3), WHITE),
        ((0, 1), BLACK), ((7, 4), WHITE),
        ((0, 2), BLACK), ((7, 5), WHITE),
        ((4, 4), BLACK), ((7, 6), WHITE),
    ]:
        board.apply_move(mv)

    # 当前轮到黑方（BLACK）；白方存在成五威胁
    opp_wins = gomoku_winning_moves(board, WHITE)
    check("白方冲四威胁点存在", len(opp_wins) >= 1)
    check("黑方自身无制胜点（确保走防守分支）", not gomoku_winning_moves(board, BLACK))

    for algo in ["alphabeta", "mcts"]:
        ai = create_ai(algo, BLACK, cfg)
        move = ai.select_move(board)
        check(f"{algo} 强制防守：落子 (7,2) 或 (7,7)",
              move in [(7, 2), (7, 7)])


def test_gomoku_forced_win() -> None:
    print("\n== 五子棋 AI 强制进攻（直接成五） ==")
    cfg = load_config([])

    board = GomokuBoard(9)
    # 黑方四连，白方占位；轮到黑方时应直接取胜
    for mv, player in [
        ((2, 2), BLACK), ((8, 8), WHITE),
        ((2, 3), BLACK), ((7, 7), WHITE),
        ((2, 4), BLACK), ((6, 6), WHITE),
        ((2, 5), BLACK), ((5, 5), WHITE),
    ]:
        board.apply_move(mv)

    my_wins = gomoku_winning_moves(board, BLACK)
    check("黑方存在成五点", len(my_wins) >= 1)

    for algo in ["alphabeta", "mcts"]:
        ai = create_ai(algo, BLACK, cfg)
        move = ai.select_move(board)
        check(f"{algo} 强制进攻：落于成五点 {my_wins[:3]}", move in my_wins)


def test_ai_think_state() -> None:
    print("\n== AI 思考过程状态（可视化数据） ==")
    cfg = load_config(["--mcts-iterations", "300", "--ab-depth", "3"])

    board = GomokuBoard(9)
    board.apply_move((4, 4))
    board.apply_move((4, 5))

    mcts = create_ai("mcts", BLACK, cfg)
    mcts.select_move(board)
    check("MCTS 思考状态记录了最佳步", mcts.think.best_move is not None)
    check("MCTS 思考状态记录了迭代数", mcts.think.done > 0)

    ab = create_ai("alphabeta", BLACK, cfg)
    ab.select_move(board)
    check("Alpha-Beta 思考状态记录了深度", ab.think.depth >= 1)
    check("Alpha-Beta 思考状态记录了最佳步", ab.think.best_move is not None)


def test_candidate_moves() -> None:
    print("\n== 五子棋候选裁剪 ==")
    board = GomokuBoard(15)
    board.apply_move((7, 7))

    cand = candidate_moves(board)
    check("候选裁剪后数量远小于全盘空位", len(cand) < 100)
    # 所有候选都应落在 (7,7) 半径 2 邻域内
    in_radius = all(
        max(abs(r - 7), abs(c - 7)) <= 2 for r, c in cand
    )
    check("全部候选在已有棋子 2 格邻域内", in_radius)
    check("候选不含已有棋子位置", (7, 7) not in cand)


# ===================== 三、对局控制器测试 =====================

def test_game_controller_modes() -> None:
    print("\n== 对局工厂与控制器推进 ==")
    cfg = load_config([])

    for mode in ["human_vs_ai", "ai_vs_ai", "human_vs_human"]:
        ctrl = create_game("gomoku", mode,
                           "mcts" if mode != "human_vs_human" else None,
                           "alphabeta" if mode == "ai_vs_ai" else None,
                           cfg, board_size=9)
        check(f"模式 {mode} 对局创建成功", ctrl.board.size == 9)

    # AI vs AI：连续推进若干步，确认控制器可自动调度且不崩溃
    ctrl = create_game("gomoku", "ai_vs_ai", "random", "random", cfg, board_size=9)
    for _ in range(6):
        if ctrl.is_over:
            break
        ctrl.step_ai()
    check("AI-PK 六步内成功落子", ctrl.board.move_count >= 1)


# ===================== 四、配置合并测试 =====================

def test_config_merge() -> None:
    print("\n== 配置合并与统一预算 ==")
    cfg = load_config(["--game", "othello"])
    check("命令行棋种覆盖生效", cfg.game == "othello")
    check("黑白棋默认棋盘尺寸 8", cfg.board_size == 8)
    # 断言跟随 settings 全局变量：验证「全局默认值被正确载入」（settings 即调参入口）
    check(f"统一预算：MCTS 迭代 {S.MCTS_ITERATIONS}",
          cfg.mcts_iterations == S.MCTS_ITERATIONS)
    check(f"统一预算：Alpha-Beta 深度 {S.AB_MAX_DEPTH}",
          cfg.ab_depth == S.AB_MAX_DEPTH)

    cfg2 = load_config(["--ab-depth", "4", "--mcts-iterations", "1000"])
    check("命令行覆盖 Alpha-Beta 深度", cfg2.ab_depth == 4)
    check("命令行覆盖 MCTS 迭代", cfg2.mcts_iterations == 1000)


# ===================== 测试入口 =====================

if __name__ == "__main__":
    test_gomoku_rules()
    test_othello_rules()
    test_go_rules()
    test_ai_on_active_games()
    test_gomoku_forced_defense()
    test_gomoku_forced_win()
    test_ai_think_state()
    test_candidate_moves()
    test_game_controller_modes()
    test_config_merge()

    print(f"\n测试结果：{passed} 通过，{failed} 失败")
    if failed == 0:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("TESTS FAILED")
        sys.exit(1)
