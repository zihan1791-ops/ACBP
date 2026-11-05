# -*- coding: utf-8 -*-
"""
外观皮肤无头冒烟测试（虚拟显示驱动，不弹窗口）
=====================================================================

覆盖验收点：
1. 默认皮肤 paper / classic 无贴图，颜色令牌与 theme.py 原值一致；
2. 棋盘 3 套 × 棋子 3 套共 9 种组合均可渲染，且彼此画面确实不同；
3. 任意组合下黑白子中心像素可区分，坐标字 / 网格与棋盘底对比度达标；
4. 换肤不改变 BoardView 的坐标换算契约；
5. 选择写入 user_prefs.json 后重启（重载内存态）仍生效，reset 可恢复默认；
6. 贴图缺失 / 损坏时自动回退纯色绘制，游戏不崩；
7. 外观设置页可渲染、点击卡片即时生效、「恢复默认」有效；
8. 主菜单「外观设置」入口 → 设置页 → 返回，开局设定不丢失。

测试结束会还原测试前的 user_prefs.json，不污染玩家的真实偏好。
运行：python tests/skins_smoke_test.py
"""

import hashlib
import os
import sys

os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from config.args import load_config
from core.base_board import BLACK, WHITE
from game.modes import create_game
from ui import theme, skins, motion
from ui.app import App
from ui.board_view import BoardView
from ui.main_menu import MainMenu
from ui.settings_scene import AppearanceScene

PASSED = 0


def check(condition: bool, label: str) -> None:
    global PASSED
    if not condition:
        raise AssertionError("[FAIL] " + label)
    PASSED += 1
    print("[PASS] " + label)


def digest(surface: pygame.Surface) -> str:
    return hashlib.md5(pygame.image.tostring(surface, "RGB")).hexdigest()


def luminance(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def render_board(board_id: str, stone_id: str, board,
                 size=(600, 600)) -> pygame.Surface:
    skins.set_board_skin(board_id)
    skins.set_stone_skin(stone_id)
    surf = pygame.Surface(size)
    surf.fill(theme.PAPER)
    view = BoardView((0, 0, size[0], size[1]), board)
    view.draw(surf, show_legal_hint=False)
    return surf


def main() -> None:
    prefs_path = skins.PREFS_FILE
    backup = None
    if os.path.isfile(prefs_path):
        with open(prefs_path, "rb") as fp:
            backup = fp.read()

    cfg = load_config([])
    theme.set_canvas(cfg)
    pygame.init()
    w, h = theme.window_size(cfg)
    screen = pygame.display.set_mode((w, h))
    motion.set_reduced(True)

    try:
        # ---- 1. 默认皮肤与原版逐值一致 ---------------------------------
        skins.reset()
        skins._forget_prefs()
        skins.clear_cache()
        pal = skins.board_palette("paper")
        sp = skins.stone_palette("classic")
        check(pal["bg"] == theme.BOARD_PAPER and pal["grid"] == theme.RULE,
              "默认棋盘配色等于 theme 原值")
        check(sp["black"] == theme.BLACK_STONE
              and sp["white"] == theme.WHITE_STONE,
              "默认棋子配色等于 theme 原值")
        check(skins.board_texture(200, 200, "paper") is None
              and skins.stone_texture(True, 40, "classic") is None,
              "默认皮肤不使用贴图（纯代码绘制）")

        # ---- 2. 9 种组合渲染 + 差异 + 黑白可辨 -------------------------
        ctrl = create_game("gomoku", "human_vs_human", None, None,
                           cfg, board_size=9)
        board = ctrl.board
        board.board[2][2] = BLACK
        board.board[3][3] = WHITE
        board.last_move = (2, 2)

        hashes = {}
        for bid in [s["id"] for s in skins.board_skins()]:
            for sid in [s["id"] for s in skins.stone_skins()]:
                surf = render_board(bid, sid, board)
                hashes[(bid, sid)] = digest(surf)
                view = BoardView((0, 0, 600, 600), board)
                bx, by = view.cell_center(2, 2)
                wx, wy = view.cell_center(3, 3)
                black_px = surf.get_at((int(bx), int(by)))[:3]
                white_px = surf.get_at((int(wx), int(wy)))[:3]
                check(abs(luminance(black_px) - luminance(white_px)) > 60,
                      "%s / %s 黑白子可辨" % (bid, sid))
        check(len(set(hashes.values())) == 9,
              "9 种组合画面各不相同（贴图与配色均生效）")

        # 三种棋盘底上的坐标字 / 网格对比度
        for bid in [s["id"] for s in skins.board_skins()]:
            p = skins.board_palette(bid)
            tex = skins.board_texture(64, 64, bid)
            base = tex.get_at((32, 32))[:3] if tex is not None else p["bg"]
            coord_ratio = theme.contrast(p["coord"], base)
            grid_ratio = theme.contrast(p["grid"], base)
            check(coord_ratio >= 3.0 and grid_ratio >= 2.0,
                  "%s 棋盘坐标字 %.1f:1 / 网格 %.1f:1 可读"
                  % (bid, coord_ratio, grid_ratio))

        # ---- 3. 坐标换算契约不随皮肤变化 --------------------------------
        view = BoardView((36, 96, 800, 690), board)
        probes = [(view.cell_center(r, c)) for r, c in
                  ((0, 0), (4, 4), (8, 8), (2, 6))]
        before = [view.pixel_to_cell((int(x), int(y))) for x, y in probes]
        for bid in ("wood", "ink", "paper"):
            skins.set_board_skin(bid)
            view.draw(pygame.Surface((900, 820)))
        after = [view.pixel_to_cell((int(x), int(y))) for x, y in probes]
        check(before == after, "换肤前后 pixel_to_cell 结果完全一致")

        # ---- 4. 持久化 / 恢复默认 --------------------------------------
        skins.set_board_skin("ink")
        skins.set_stone_skin("agate")
        skins._forget_prefs()          # 模拟重启：清空内存态重新读盘
        check(skins.get_board_skin() == "ink"
              and skins.get_stone_skin() == "agate",
              "偏好写入 user_prefs.json，重启后自动沿用")
        skins.reset()
        skins._forget_prefs()
        check(skins.get_board_skin() == "paper"
              and skins.get_stone_skin() == "classic",
              "恢复默认回到 paper / classic")

        # ---- 5. 缺图兜底 ------------------------------------------------
        wood = os.path.join(skins.SKIN_DIR, "board_wood.png")
        tmp = wood + ".missing_test"
        os.rename(wood, tmp)
        try:
            skins.clear_cache()
            skins._missing_reported.clear()
            check(skins.board_texture(300, 300, "wood") is None,
                  "贴图缺失时返回 None（回退纯色绘制）")
            skins.set_board_skin("wood")
            surf = pygame.Surface((600, 600))
            BoardView((0, 0, 600, 600), board).draw(surf)
            check(True, "贴图缺失时棋盘正常绘制，无异常")
        finally:
            os.rename(tmp, wood)
            skins.clear_cache()
            skins._missing_reported.clear()
            skins.reset()
            skins._forget_prefs()

        # ---- 6. 设置页渲染与点击 ----------------------------------------
        scene = AppearanceScene(cfg, on_back=lambda: None)
        scene.update()
        scene.draw(screen)
        check(True, "外观设置页构造、更新与渲染")

        card = next(wd for wd in scene.widgets
                    if hasattr(wd, "spec") and wd.kind == "board"
                    and wd.spec["id"] == "wood")
        click = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": card.rect.center})
        scene.handle_event(click)
        check(skins.get_board_skin() == "wood",
              "点击棋盘皮肤卡片即时生效并保存")
        scene.update()
        scene.draw(screen)
        check(card.selected is True, "选中卡片显示「当前使用」状态")

        reset_btn = next(wd for wd in scene.widgets
                         if getattr(wd, "text", None) == "恢复默认")
        scene.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": reset_btn.rect.center}))
        check(skins.get_board_skin() == "paper"
              and skins.get_stone_skin() == "classic",
              "设置页「恢复默认」有效")

        # ---- 7. 主菜单入口与开局设定保持 --------------------------------
        app = App(cfg)
        check(isinstance(app.scene, MainMenu), "App 启动进入主菜单")
        # 先改一次开局设定，验证返回后不丢失
        app.scene._set("game_kind", "othello")
        app.scene._set("mode", "human_vs_human")
        expected = app.scene.current_options()

        entry = next(b for b in app.scene.buttons
                     if getattr(b, "text", None) == "外观设置")
        app.scene.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": entry.rect.center}))
        check(isinstance(app.scene, AppearanceScene),
              "主菜单「外观设置」按钮进入设置页")
        app.scene.draw(screen)

        back = next(wd for wd in app.scene.widgets
                    if getattr(wd, "text", None) == "返回主菜单")
        app.scene.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": back.rect.center}))
        check(isinstance(app.scene, MainMenu), "设置页返回主菜单")
        check(app.scene.current_options() == expected,
              "返回主菜单后开局设定原样保留")

        # ---- 8. 回放 / 对局场景共用同一皮肤 -----------------------------
        skins.set_board_skin("ink")
        skins.set_stone_skin("jade")
        from ui.game_scene import GameScene
        gscene = GameScene(ctrl, on_back=lambda: None)
        gscene.draw(screen)
        check(True, "对局场景应用当前皮肤渲染无异常")
        skins.reset()
        skins._forget_prefs()

        print("\nSKINS SMOKE PASSED（%d 项）" % PASSED)
    finally:
        # 还原玩家原有偏好文件（没有则删除测试生成的文件）
        if backup is not None:
            with open(prefs_path, "wb") as fp:
                fp.write(backup)
        elif os.path.isfile(prefs_path):
            os.remove(prefs_path)
        skins._forget_prefs()
        skins.clear_cache()
        pygame.quit()


if __name__ == "__main__":
    main()
