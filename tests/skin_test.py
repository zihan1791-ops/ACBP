# -*- coding: utf-8 -*-
"""
棋子外观测试（无头）。

覆盖内容：
1. 皮肤注册表、默认外观、非法标识归一；
2. 旧棋谱缺 skin 字段时回退经典纯色；
3. Player / GameController / create_game / resume 的皮肤链路；
4. 头像资源加载、圆形缓存与缺图回退；
5. BoardView 与主菜单弹层的无头绘制。

运行方式（项目根目录下）：
    python tests/skin_test.py
全部通过时末尾输出 "ALL SKIN TESTS PASSED"。
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from config.args import load_config
from config.skins import (SKIN_ORDER, from_record, is_valid, label,
                          normalize)
from core.base_board import BLACK, WHITE
from core.gomoku.board import GomokuBoard
from game.modes import create_game, resume_game_from_record
from game.player import Player
from ui import piece_skins
from ui.board_view import BoardView
from ui.main_menu import MainMenu


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


def main() -> int:
    cfg = load_config([])

    # ---- 注册表与归一 ----
    check("皮肤注册表包含四套外观",
          SKIN_ORDER == ("classic", "ember", "azure", "violet"))
    check("默认外观为黑橙发 / 白蓝发",
          normalize(None, BLACK) == "ember"
          and normalize(None, WHITE) == "azure")
    check("非法标识回退默认或经典",
          normalize("bogus", BLACK) == "ember"
          and normalize("bogus", 9) == "classic")
    check("经典外观合法且有中文标签",
          is_valid("classic") and label("classic") == "经典")
    check("旧棋谱缺字段时回退经典",
          from_record({}) == {BLACK: "classic", WHITE: "classic"})
    check("棋谱外观按黑 / 白分别读取",
          from_record({"players": {
              "black": {"skin": "violet"},
              "white": {"skin": "azure"},
          }}) == {BLACK: "violet", WHITE: "azure"})
    check("棋谱中的非法外观回退经典",
          from_record({"players": {
              "black": {"skin": "bogus"},
              "white": {"skin": "azure"},
          }}) == {BLACK: "classic", WHITE: "azure"})

    # ---- Player 与对局链路 ----
    check("Player 默认外观",
          Player(BLACK, "黑方").skin == "ember"
          and Player(WHITE, "白方").skin == "azure")
    check("Player 接受显式外观",
          Player(BLACK, "黑方", None, "violet").skin == "violet")

    ctrl = create_game("gomoku", "human_vs_ai", None, "random", cfg,
                       skins={BLACK: "violet", WHITE: "ember"})
    check("create_game 透传双方外观",
          ctrl.skins == {BLACK: "violet", WHITE: "ember"}
          and ctrl.players[BLACK].skin == "violet"
          and ctrl.players[WHITE].skin == "ember")

    record = {
        "game": "gomoku",
        "board_size": 15,
        "moves": [{"player": BLACK, "move": [7, 7]},
                  {"player": WHITE, "move": [7, 8]}],
        "players": {
            "black": {"type": "human", "skin": "violet"},
            "white": {"type": "ai", "ai": "random", "skin": "ember"},
        },
    }
    resumed = resume_game_from_record(record, cfg)
    check("续局恢复棋谱外观",
          resumed.skins == {BLACK: "violet", WHITE: "ember"})
    check("续局同时恢复步数", resumed.board.move_count == 2)

    legacy = {
        "game": "gomoku",
        "board_size": 15,
        "moves": [],
        "players": {
            "black": {"type": "human"},
            "white": {"type": "ai", "ai": "random"},
        },
    }
    old = resume_game_from_record(legacy, cfg)
    check("旧棋谱续局使用经典棋子",
          old.skins == {BLACK: "classic", WHITE: "classic"})

    # ---- 资源层与绘制 ----
    pygame.init()
    pygame.display.set_mode((160, 160))

    check("头像资源可加载为圆形表面",
          piece_skins.face("ember", 40) is not None
          and piece_skins.face("ember", 40).get_size() == (40, 40))
    check("经典外观不返回图片", piece_skins.face("classic", 40) is None)

    board = GomokuBoard(15)
    board.apply_move((7, 7))
    board.apply_move((7, 8))
    surface = pygame.Surface((800, 690))
    view = BoardView(pygame.Rect(0, 0, 800, 690), board,
                     skins={BLACK: "ember", WHITE: "violet"})
    view.draw(surface)
    view.set_skins({BLACK: "classic", WHITE: "classic"})
    view.draw(surface)
    check("BoardView 头像与纯色分支均可绘制", True)

    origin_dir = piece_skins.IMAGE_DIR
    piece_skins.IMAGE_DIR = Path(tempfile.mkdtemp(prefix="acbp_skins_"))
    piece_skins.clear_cache()
    missing = piece_skins.face("ember", 40)
    piece_skins.IMAGE_DIR = origin_dir
    piece_skins.clear_cache()
    check("缺图时回退纯色（face 返回 None）", missing is None)

    # ---- 主菜单弹层 ----
    changed = {}
    menu = MainMenu(cfg, lambda options: None, None,
                    skins={BLACK: "ember", WHITE: "azure"},
                    on_skins_change=lambda skins: changed.update(skins))
    menu._open_skins_modal()
    check("弹层打开并生成九个按钮",
          menu.modal == "skins" and len(menu.modal_buttons) == 9)
    menu._set_skin(BLACK, "violet")
    check("弹层选择同步到菜单与回调",
          menu.skins[BLACK] == "violet" and changed.get(BLACK) == "violet")
    menu._draw_modal(pygame.Surface((1440, 900)))
    menu._close_modal()
    check("弹层可关闭并归还焦点", menu.modal is None)

    pygame.quit()

    print()
    if failed:
        print(f"{failed} test(s) failed, {passed} passed")
        return 1
    print("ALL SKIN TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
