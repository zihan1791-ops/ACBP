# -*- coding: utf-8 -*-
"""
pygame 应用主循环与场景切换器。

场景流转：
    主菜单 MainMenu ──选择参数并点击开始──► 对局场景 GameScene
    主菜单 MainMenu ──棋谱回放──► 回放场景 ReplayScene
    对局 / 回放 ──返回主菜单──► 主菜单 MainMenu

若 settings.py / 命令行已同时指定棋种与模式，程序启动后直接进入对局场景；
否则先进入主菜单由玩家可视化选择。
"""

import pygame

from . import theme
from .main_menu import MainMenu
from .game_scene import GameScene
from .replay_scene import ReplayScene
from game.modes import create_game, resume_game_from_record
from utils.logger import log_info


class App:
    """应用顶层控制器：持有窗口、时钟与当前场景。"""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

        # pygame 初始化与窗口创建（物理像素尺寸，适配高分屏缩放）
        pygame.init()
        pygame.display.set_caption("棋类综合对战平台 · 五子棋 / 黑白棋")
        w = theme.S(cfg.window_width)
        h = theme.S(cfg.window_height)
        self.screen = pygame.display.set_mode((w, h))
        self.clock = pygame.time.Clock()

        self.running = True
        self.controller = None
        self.scene = None

        # 配置已完整指定棋种与模式：直接开局；否则进入主菜单
        if cfg.game and cfg.mode:
            self._start_game({
                "game_kind": cfg.game,
                "mode": cfg.mode,
                "p1_ai": cfg.p1_ai,
                "p2_ai": cfg.p2_ai,
                "board_size": cfg.board_size,
            })
        else:
            self.scene = MainMenu(self.cfg, self._on_menu_start,
                                  on_replay=self._open_replay)

    # ===================== 场景切换 =====================

    def _on_menu_start(self, options: dict) -> None:
        """主菜单点击「开始对局」后的回调：创建对局并切换场景。"""
        self._start_game(options)

    def _open_replay(self) -> None:
        """主菜单点击「棋谱回放」后的回调：进入棋谱回放场景。"""
        self.scene = ReplayScene(self.cfg, self._back_to_menu,
                                 on_resume=self._resume_from_replay)

    def _back_to_menu(self) -> None:
        """从对局 / 回放场景返回主菜单。"""
        self.scene = MainMenu(self.cfg, self._on_menu_start,
                              on_replay=self._open_replay)

    def _resume_from_replay(self, record: dict, step: int,
                            p1_ai=None, p2_ai=None) -> None:
        """
        回放场景「从这继续对局」回调：以回放点局面恢复一局并进入对局场景。

        双方角色默认按棋谱记录还原；回放设置中显式指定时以指定角色为准
        （None 表示人类，算法名表示由该 AI 介入）。历史落子预填进棋谱，
        保证继续对局终局保存的棋谱包含从开局到结束的全部手数。
        """
        self.controller = resume_game_from_record(
            record, self.cfg, step, p1_ai=p1_ai, p2_ai=p2_ai)
        # 预填历史落子，保证继续对局终局保存的棋谱包含完整手数
        self.controller.moves = [dict(mv) for mv in record.get("moves", [])[:step]]
        self.scene = GameScene(self.controller, self._back_to_menu)
        log_info(f"已从棋谱第 {step} 手继续对局："
                 f"{record['game']} / {record.get('board_size')} 路")

    def _start_game(self, options: dict) -> None:
        """根据菜单 / 配置选项组装对局控制器并切换到对局场景。"""
        self.controller = create_game(
            game_kind=options["game_kind"],
            mode=options["mode"],
            p1_ai_name=options.get("p1_ai"),
            p2_ai_name=options.get("p2_ai"),
            config=self.cfg,
            board_size=options.get("board_size"),
        )
        self.scene = GameScene(self.controller, self._back_to_menu)

        log_info(f"新对局开始：{options['game_kind']} / {options['mode']}，"
                 f"棋盘 {self.controller.board_size} 路")

    # ===================== 主循环 =====================

    def run(self) -> None:
        """启动事件循环：事件分发 → 场景更新 → 场景绘制 → 刷新画面。"""
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                # 事件先交给当前场景处理（按钮 / 棋盘点击等）
                if self.scene is not None:
                    self.scene.handle_event(event)

            if self.scene is not None:
                self.scene.update()
                self.scene.draw(self.screen)

            pygame.display.flip()
            self.clock.tick(self.cfg.fps)

        pygame.quit()
