# -*- coding: utf-8 -*-
"""
象棋棋盘版式 / 起止点 / 禁止连续重复走法 + 黑白棋子数常驻 / 结算比分 回归测试。

覆盖：
1. 象棋盘像素级版式：河界处中间竖线断开、左右边线贯通、九宫米字斜线、
   炮位与兵位 L 形标记；
2. 最后一手同时标注起点（朱砂点 + 轨迹）与落点（四角括号）；
3. 「不能连续走一样的步」规则：第 3 次重复着法被过滤 / 拒绝、提示文案、
   copy 与 push/pop 状态同步、变着后计数重置、七类算法仍返回合法步；
4. 黑白棋悔棋 / 重开后子数文本常驻且数值随棋盘刷新，事件提示独立一行并限时；
5. 终局结算遮罩显示比分。

运行方式（项目根目录下）：
    python tests/board_ui_rules_test.py
全部通过时末尾输出 "BOARD UI RULES TESTS PASSED"。
"""

import os
import random
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from ai.factory import create_ai
from config.args import load_config
from core.chess.board import ChessBoard, encode_sq, decode_sq, REPEAT_LIMIT
from core.base_board import BLACK, WHITE
from game.modes import create_game
from ui import theme
from ui.app import App
from ui.board_view import BoardView
import ui.game_scene as game_scene

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


def move(a, b):
    return (encode_sq(*a), encode_sq(*b))


def rendered_texts(scene, surface):
    """捕获一次 draw 中经 assets.mixed 渲染的全部文案，用于断言版面内容。"""
    orig = game_scene.assets.mixed
    seen = []

    def spy(size, text, color):
        seen.append(text)
        return orig(size, text, color)

    game_scene.assets.mixed = spy
    try:
        scene.update()
        scene.draw(surface)
    finally:
        game_scene.assets.mixed = orig
    return seen


def main() -> None:
    pygame.init()

    # ---------- 1. 象棋棋盘版式（像素级） ----------
    surf = pygame.Surface((1000, 1000))
    board = ChessBoard(10)
    # 版式验证用空棋盘：棋子不会遮住炮位 / 兵位标记与九宫斜线
    blank = ChessBoard(10)
    blank.board = [[0 for _ in range(9)] for _ in range(10)]
    view = BoardView((50, 50, 840, 900), blank)
    view.draw(surf)
    ox, oy, cell = view.origin_x, view.origin_y, view.cell
    paper = theme.BOARD_PAPER

    def px(x, y):
        return surf.get_at((int(round(x)), int(round(y))))[:3]

    def ink_near(x, y, radius=3):
        """1px 线段存在取整偏差，用邻域扫描判断是否绘制过墨线。"""
        return any(px(x + dx, y + dy) != paper
                   for dx in range(-radius, radius + 1)
                   for dy in range(-radius, radius + 1))

    y_river, y_solid = oy + 4.5 * cell, oy + 3.5 * cell
    check("楚河汉界处中间竖线断开",
          px(ox + cell, y_river) == paper)
    check("非河界区域竖线保留", ink_near(ox + cell, y_solid, 1))
    check("左右边线在河界处贯通",
          ink_near(ox, y_river, 2) and ink_near(ox + 8 * cell, y_river, 2))
    check("上下九宫米字斜线已绘制",
          ink_near(ox + 3.5 * cell, oy + 0.5 * cell) and
          ink_near(ox + 3.5 * cell, oy + 8.5 * cell))

    gap = max(theme.S(7), int(cell * 0.25))
    arm = max(theme.S(5), int(cell * 0.13))
    cx, cy = view.cell_center(2, 1)          # 炮位
    bx, by = view.cell_center(3, 4)          # 兵位
    check("炮位 L 形定位标记", ink_near(cx - (gap + arm), cy - gap))
    check("兵位 L 形定位标记", ink_near(bx - (gap + arm), by - gap))
    # 标准 L 的拐角在内侧、两臂向外；外角点若有墨色说明又画成了方框四角
    check("兵炮位标记不是框型（外角点无墨）",
          px(cx + (gap + arm), cy - (gap + arm)) == paper and
          not ink_near(cx + (gap + arm), cy - (gap + arm), 1))
    edge_x, edge_y = view.cell_center(3, 0)  # 贴边兵位：只画内侧两角
    check("贴边兵位标记只画内侧、不越出棋盘",
          ink_near(edge_x + (gap + arm), edge_y - gap) and
          not ink_near(edge_x - (gap + arm), edge_y - gap))

    # ---------- 2. 起始点 + 落点 ----------
    board.apply_move(move((7, 1), (7, 4)))
    view.board = board
    view.draw(surf)
    sx, sy = view.cell_center(7, 1)
    dx, dy = view.cell_center(7, 4)
    check("最后一手起点有朱砂标记", px(sx, sy) == theme.CINNABAR)
    length = max(4, int(cell * 0.12))
    side = int(cell * 0.74)
    check("最后一手落点有四角括号",
          any(px(dx - side / 2 + i, dy - side / 2 + j) == theme.CINNABAR
              for i in range(length + 2) for j in range(3)))
    half = int(cell * 0.58) / 2
    check("起点空心方框已绘制", ink_near(sx + half, sy + cell * 0.10, 2))

    # ---------- 3. 禁止连续重复走法 ----------
    b = ChessBoard(10)
    seq = [(BLACK, move((7, 1), (7, 4))),
           (WHITE, move((0, 7), (2, 6))),
           (BLACK, move((7, 4), (7, 1))),
           (WHITE, move((0, 1), (2, 2)))]
    ok = True
    for side_, mv in seq:
        ok = ok and side_ == b.current_player and mv in b.get_legal_moves()
        ok = ok and b.apply_move(mv)
    check("允许一次来回试探（streak 累计到 2）",
          ok and b._repeat_streak[BLACK] == 2)
    check("阈值配置为 3", REPEAT_LIMIT == 3)

    third = move((7, 1), (7, 4))
    snapshot = ([row[:] for row in b.board], b.move_count, b.current_player,
                dict(b._repeat_streak), dict(b._last_own_move))
    check("第 3 次重复着法从合法步中移除", third not in b.get_legal_moves())
    check("第 3 次重复着法被 apply_move 拒绝", not b.apply_move(third))
    check("拒绝后棋盘状态零变化",
          ([row[:] for row in b.board], b.move_count, b.current_player,
           b._repeat_streak, b._last_own_move) == snapshot)
    check("违规提示文案可读", "变着" in b.repeat_block_reason(third))

    clone = b.copy()
    check("copy 同步重复状态",
          clone._repeat_streak == b._repeat_streak and
          clone._last_own_move == b._last_own_move)
    before = (clone._repeat_streak[BLACK], clone._last_own_move[BLACK],
              clone.move_count)
    other = move((9, 0), (8, 0))
    check("push 接受非重复着法", clone.push(other))
    check("push 后 streak 重置为 1", clone._repeat_streak[BLACK] == 1)
    check("pop 完整还原重复状态",
          clone.pop() and
          (clone._repeat_streak[BLACK], clone._last_own_move[BLACK],
           clone.move_count) == before)
    check("变着后禁令解除", b.apply_move(other) and b._repeat_streak[BLACK] == 1)

    # 人类入口给出专门提示
    cfg = load_config(["--game", "chess", "--mode", "human_vs_human"])
    ctrl = create_game("chess", "human_vs_human", None, None, cfg)
    for mv in (seq[0][1], seq[1][1], seq[2][1], seq[3][1]):
        ctrl.board.apply_move(mv)
    ctrl.handle_human_move(third)
    check("人类点击重复步提示「须变着」", "变着" in ctrl.last_event)
    check("规则不常驻面板（统计栏为空）", ctrl.score_text() == "")
    check("象棋按将死判胜、无比分", ctrl.score_line() == "")

    fast = load_config(["--mcts-iterations", "25", "--mcts-time", "0.3",
                        "--ab-depth", "2", "--ab-time", "0.3",
                        "--evo-population", "6", "--evo-generations", "3",
                        "--evo-horizon", "3", "--evo-time", "0.4", "--seed", "5"])
    legal_all = True
    for algo in ("mcts", "alphabeta", "random", "iga", "de", "pso", "abc"):
        cb = ChessBoard(10)
        for mv in (seq[0][1], seq[1][1], seq[2][1], seq[3][1]):
            cb.apply_move(mv)
        mv = create_ai(algo, cb.current_player, fast).select_move(cb)
        legal_all = legal_all and mv in cb.get_legal_moves()
    check("七类算法在禁令局面仍返回合法步", legal_all)

    # ---------- 4. 将军弹窗 ----------
    cfg_c = load_config(["--game", "chess", "--mode", "human_vs_human"])
    app_c = App(cfg_c)
    ctrl_c = create_game("chess", "human_vs_human", None, None, cfg_c)
    cb = ctrl_c.board
    cb.board = [[0 for _ in range(9)] for _ in range(10)]
    cb.board[9][4] = 11          # 红帅
    cb.board[0][4] = 21          # 黑将
    cb.board[8][4] = 25          # 黑车同列直线将军
    cb.current_player = BLACK
    check("规则层能判定将军", cb.in_check())
    scene_c = game_scene.GameScene(ctrl_c, lambda: None)
    alert_texts = rendered_texts(scene_c, app_c.screen)
    check("将军时弹出醒目弹窗", any("将 军！" in t for t in alert_texts))
    check("弹窗显示「须应将」说明",
          any("须应将 · 请先解将" in t for t in alert_texts))
    check("将军期间角标常驻",
          any("将 军 · 须应将" in t for t in alert_texts))

    scene_c._check_alert_at = time.time() - 10
    expired = rendered_texts(scene_c, app_c.screen)
    check("弹窗 3 秒后收起、角标仍在",
          not any("将 军！" in t for t in expired) and
          any("将 军 · 须应将" in t for t in expired))

    cb.board[8][4] = 0           # 移走黑车，解除将军
    cleared = rendered_texts(scene_c, app_c.screen)
    check("解将后提示全部消失",
          not any("将 军" in t for t in cleared))

    # ---------- 5. 黑白棋子数常驻 / 事件限时 ----------
    cfg_o = load_config(["--game", "othello", "--mode", "human_vs_human"])
    app_o = App(cfg_o)
    ctrl_o = create_game("othello", "human_vs_human", None, None, cfg_o)
    scene = game_scene.GameScene(ctrl_o, lambda: None)
    screen = app_o.screen
    rng = random.Random(5)
    for _ in range(6):
        lm = ctrl_o.board.get_legal_moves()
        if not lm:
            break
        ctrl_o._push_snapshot()
        ctrl_o.board.apply_move(rng.choice(lm))

    ctrl_o.undo(1)
    ctrl_o.last_event = "已悔棋 1 步"
    texts = rendered_texts(scene, screen)
    check("悔棋后子数文本仍渲染",
          any("黑方" in t and "白方" in t and "子" in t for t in texts))
    check("悔棋事件独立一行渲染", any("悔棋" in t for t in texts))
    check("统计行与事件行不重合",
          game_scene.GameScene.LAYOUT["score"] !=
          game_scene.GameScene.LAYOUT["event"])

    scene._last_event_at = time.time() - 10
    texts_expired = rendered_texts(scene, screen)
    check("事件超时后消失而子数常驻",
          not any("悔棋" in t for t in texts_expired) and
          any("黑方" in t and "子" in t for t in texts_expired))

    ctrl_o.restart()
    ctrl_o.last_event = "对局已重新开始"
    texts_restart = rendered_texts(scene, screen)
    check("重开后子数刷新为开局 2:2",
          ctrl_o.score_line() == "黑方 2 子 : 白方 2 子" and
          any("黑方 2 子" in t for t in texts_restart) and
          any("重新开始" in t for t in texts_restart))

    # ---------- 6. 结算比分 ----------
    ctrl_o.board.game_over = True
    ctrl_o.board.winner = BLACK
    texts_result = rendered_texts(scene, screen)
    score_hits = [t for t in texts_result if "黑方" in t and "白方" in t and ":" in t]
    check("结算时比分同时出现在对局栏与遮罩", len(score_hits) >= 2)
    check("非象棋棋种不显示将军提示",
          not any("将 军" in t for t in texts_result))

    pygame.quit()
    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("BOARD UI RULES TESTS PASSED")


if __name__ == "__main__":
    main()
