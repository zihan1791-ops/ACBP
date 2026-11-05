# -*- coding: utf-8 -*-
"""
pygame 应用主循环与场景切换器（≈ 路由表）。

场景流转与全部跨层契约保持不变：
    MainMenu ──开始对局──► GameScene ──返回──► MainMenu
    MainMenu ──棋谱回放──► ReplayScene ──续局──► GameScene
    MainMenu ──外观设置──► AppearanceScene ──返回──► MainMenu
    cfg.game 与 cfg.mode 同时指定时直接开局。
    App(cfg) / run() / scene / screen / clock / controller / running 均保持。

新增（纯前端）：启动时打印设计自检，R 键切换 reduced-motion，
统一按 R 关闭全部入场与微交互动效。
"""

import pygame

from . import theme, motion, assets, ai_runner
from .main_menu import MainMenu
from .settings_scene import AppearanceScene
from .game_scene import GameScene
from .replay_scene import ReplayScene
from game.modes import create_game, resume_game_from_record
from utils.logger import log_info


class App:
    """应用顶层控制器：持有窗口、时钟与当前场景。"""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

        # 先按实际窗口尺寸重算画布缩放与全部字号/间距令牌，再创建窗口
        theme.set_canvas(cfg)
        pygame.init()
        # 真实窗口模式：启动时预热长驻 worker，首个 AI 回合不再有 spawn 卡顿
        if ai_runner.default_mode() == "async":
            ai_runner.warmup()
        pygame.display.set_caption("ACBP · 棋类综合对战平台")
        w, h = theme.window_size(cfg)
        self.screen = pygame.display.set_mode((w, h))
        self.clock = pygame.time.Clock()

        theme.qa_report(cfg)
        assets.font_report()
        print("-" * 62)

        self.running = True
        self.controller = None
        self.scene = None
        self._menu_options = None      # 主菜单选择快照，供设置页 / 对局返回时恢复

        if cfg.game and cfg.mode:
            self._start_game({
                "game_kind": cfg.game,
                "mode": cfg.mode,
                "p1_ai": cfg.p1_ai,
                "p2_ai": cfg.p2_ai,
                "board_size": cfg.board_size,
            })
        else:
            self._set_scene(MainMenu(self.cfg, self._on_menu_start,
                                     on_replay=self._open_replay,
                                     on_settings=self._open_settings))

    # ===================== 场景切换（契约） =====================

    def _set_scene(self, scene) -> None:
        """切换场景前关闭旧对局场景的长驻 AI worker，避免进程残留。"""
        if self.scene is not None and hasattr(self.scene, "shutdown_ai"):
            self.scene.shutdown_ai()
        self.scene = scene

    def _on_menu_start(self, options: dict) -> None:
        """主菜单点击「开始对局」后的回调。"""
        self._menu_options = dict(options)
        self._start_game(options)

    def _open_replay(self) -> None:
        """主菜单点击「棋谱回放」后的回调。"""
        self._remember_menu()
        self._set_scene(ReplayScene(self.cfg, self._back_to_menu,
                                    on_resume=self._resume_from_replay))

    def _open_settings(self) -> None:
        """主菜单点击「外观设置」后的回调：进入独立外观设置页。"""
        self._remember_menu()
        self._set_scene(AppearanceScene(self.cfg, self._back_to_menu))

    def _remember_menu(self) -> None:
        """离开主菜单前记下当前开局设定，返回时原样恢复。"""
        if isinstance(self.scene, MainMenu):
            self._menu_options = self.scene.current_options()

    def _back_to_menu(self) -> None:
        """从对局 / 回放 / 外观设置场景返回主菜单。"""
        self._set_scene(MainMenu(self.cfg, self._on_menu_start,
                                 on_replay=self._open_replay,
                                 on_settings=self._open_settings,
                                 initial_options=self._menu_options))

    def _resume_from_replay(self, record: dict, step: int,
                            p1_ai=None, p2_ai=None) -> None:
        """回放「从这继续对局」回调：恢复局面并预填历史落子。"""
        self.controller = resume_game_from_record(
            record, self.cfg, step, p1_ai=p1_ai, p2_ai=p2_ai)
        self.controller.moves = [dict(mv) for mv in record.get("moves", [])[:step]]
        self._set_scene(GameScene(self.controller, self._back_to_menu))
        log_info("已从棋谱第 %d 手继续对局：%s / %s 路"
                 % (step, record["game"], record.get("board_size")))

    def _start_game(self, options: dict) -> None:
        """组装对局控制器并切换到对局场景。"""
        self.controller = create_game(
            game_kind=options["game_kind"],
            mode=options["mode"],
            p1_ai_name=options.get("p1_ai"),
            p2_ai_name=options.get("p2_ai"),
            config=self.cfg,
            board_size=options.get("board_size"),
        )
        self._set_scene(GameScene(self.controller, self._back_to_menu))
        log_info("新对局开始：%s / %s，棋盘 %s 路"
                 % (options["game_kind"], options["mode"],
                    self.controller.board_size))

    # ===================== 主循环 =====================

    def run(self) -> None:
        """事件分发 → 场景更新 → 场景绘制 → 刷新画面。"""
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    reduced = motion.toggle_reduced()
                    log_info("界面动效：%s" % ("关闭" if reduced else "开启"))
                if self.scene is not None:
                    self.scene.handle_event(event)

            if self.scene is not None:
                self.scene.update()
                self.scene.draw(self.screen)

            pygame.display.flip()
            self.clock.tick(self.cfg.fps)

        if self.scene is not None and hasattr(self.scene, "shutdown_ai"):
            self.scene.shutdown_ai()
        ai_runner.shutdown_shared()
        pygame.quit()
