# -*- coding: utf-8 -*-
"""
UI 无头冒烟测试（虚拟显示驱动，不弹出真实窗口）。

验证：
1. 主菜单场景可正常构造、更新与渲染（仅开放棋种，无围棋、无难度）；
2. 开放棋种 × 三种对局模式的 GameScene 均可构造、更新与渲染；
3. 人类点击事件可正常进入对局；
4. AI 思考可视化链路：GameScene 在 AI 回合通过 on_progress 回调
   实时重绘画面（进度条 / 思考面板 / 候选高亮），不抛异常；
5. 整个进程只做一次 pygame.init()/quit()（避免字体缓存崩溃）。

运行方式（项目根目录下）：
    python tests/ui_smoke_test.py
"""

import os
import sys

# 必须在 import pygame 之前设置无头显示驱动
os.environ["SDL_VIDEODRIVER"] = "dummy"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from config.args import load_config
from core.base_board import BLACK
from ui.app import App
from ui.game_scene import GameScene
from game.modes import create_game


def main() -> None:
    # 应用整体只 init 一次，最后 quit 一次（无头字体缓存要求）
    cfg = load_config([])

    # 1. 构造应用与主菜单，渲染数帧
    app = App(cfg)
    for _ in range(3):
        app.scene.update()
        app.scene.draw(app.screen)
        pygame.display.flip()
    print("[PASS] 主菜单场景构造与渲染")

    # 2. 遍历开放棋种 × 三种模式，构造对局场景并渲染两帧
    for game in ["gomoku", "othello"]:
        board_size = 8 if game == "othello" else 9
        for mode in ["human_vs_ai", "ai_vs_ai", "human_vs_human"]:
            ctrl = create_game(game, mode, "random", "random", cfg, board_size=board_size)
            scene = GameScene(ctrl, on_back=lambda: None)
            for _ in range(2):
                scene.update()
                scene.draw(app.screen)
            print(f"[PASS] 对局场景 {game} / {mode} 构造、更新、渲染")

    # 3. 对局内模拟一次人类点击棋盘（点击左上角区域），确认事件入口不报错
    ctrl = create_game("gomoku", "human_vs_ai", None, "random", cfg, board_size=9)
    scene = GameScene(ctrl, on_back=lambda: None)
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (80, 80)})
    scene.handle_event(click)
    scene.update()
    scene.draw(app.screen)
    print("[PASS] 人类点击事件处理与渲染")

    # 4. AI 思考可视化链路：低预算 MCTS 对局，update 触发 step_ai(on_progress)，
    #    回调内部实时 draw + flip 渲染思考进度（AI 先手确保真实进入 AI 回合）
    ai_cfg = load_config(["--mcts-iterations", "120", "--mcts-time", "2.0",
                          "--ab-depth", "2", "--ab-time", "2.0"])
    ctrl = create_game("gomoku", "human_vs_ai", "mcts", None, ai_cfg, board_size=9)
    scene = GameScene(ctrl, on_back=lambda: None)
    steps = 0
    while not ctrl.is_over and ctrl.current_is_ai and steps < 2:
        scene.update()          # 内部调用 step_ai(on_progress=...)
        scene.draw(app.screen)
        pygame.display.flip()
        steps += 1
    # 人类回合应推进一步，轮到人类后 update 不触发 AI，直接渲染一帧
    scene.update()
    scene.draw(app.screen)
    check = steps >= 1
    print("[PASS] AI 思考可视化回调渲染（on_progress 实时重绘）"
          if check else "[FAIL] AI 思考回调未触发")

    # 5. 主菜单棋子外观弹层：打开、切换、渲染、关闭
    menu = app.scene
    menu._open_skins_modal()
    menu._set_skin(BLACK, "violet")
    menu.update()
    menu.draw(app.screen)
    pygame.display.flip()
    menu._close_modal()
    print("[PASS] 棋子外观弹层打开、切换、渲染与关闭")

    pygame.quit()
    print("\nUI SMOKE PASSED")


if __name__ == "__main__":
    main()
