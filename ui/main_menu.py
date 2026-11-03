# -*- coding: utf-8 -*-
"""
主菜单场景。

功能：
1. 可视化选择棋种（五子棋 / 黑白棋）、对局模式、双方算法与棋盘尺寸；
2. 若 start.py / settings.py 已指定固定参数，菜单初始状态会沿用这些默认值；
3. 点击「开始对局」后把选择结果通过回调交给 App 创建对局控制器。

布局：标题 + 若干横向选项组 + 底部开始按钮，整体保持清新统一风格。
"""

import pygame
from typing import Callable, Optional, Dict, List, Tuple

from . import theme
from .widgets import Button, draw_text
from config import GAME_DEFAULTS, VALID_GAMES, VALID_MODES, VALID_AIS


class MainMenu:
    """开局主菜单界面。"""

    # 选项中文显示映射（围棋已暂停启用，不再出现在菜单）
    GAME_LABELS: Dict[str, str] = {"gomoku": "五子棋", "othello": "黑白棋"}
    MODE_LABELS: Dict[str, str] = {
        "human_vs_ai": "人机大战",
        "ai_vs_ai": "算法 PK",
        "human_vs_human": "人人对战",
    }
    AI_LABELS: Dict[Optional[str], str] = {
        None: "人类", "mcts": "MCTS", "alphabeta": "Alpha-Beta",
        "random": "随机", "llm": "大模型",
    }

    def __init__(self, cfg, on_start: Callable[[dict], None],
                 on_replay: Optional[Callable[[], None]] = None,
                 on_llm_settings: Optional[Callable[[], None]] = None) -> None:
        self.cfg = cfg
        self.on_start = on_start
        self.on_replay = on_replay
        self.on_llm_settings = on_llm_settings

        # 初始选项：优先使用配置中已指定的值，否则采用默认
        self.game_kind: str = cfg.game or "gomoku"
        self.mode: str = cfg.mode or "human_vs_ai"
        self.p1_ai: Optional[str] = cfg.p1_ai
        self.p2_ai: Optional[str] = cfg.p2_ai
        self.board_size: Optional[int] = cfg.board_size

        self.buttons: List[Button] = []
        self._normalize_for_mode()   # 按模式归一化初始双方身份
        self._build_layout()

    # ===================== 模式与身份联动 =====================

    def _player_options(self, key: str) -> List[Tuple[Optional[str], str]]:
        """
        返回某个身份行可选的选项列表（随模式联动）：
        - 人人对战：该方只能是人类；
        - 算法 PK：  该方只能是算法（无人类）；
        - 人机大战：人类 / 算法均可选，由联动逻辑保证恰好一方人类、一方 AI。
        """
        if self.mode == "human_vs_human":
            return [(None, self.AI_LABELS[None])]
        if self.mode == "ai_vs_ai":
            return [(k, self.AI_LABELS[k]) for k in VALID_AIS]
        return [(None, self.AI_LABELS[None])] + \
            [(k, self.AI_LABELS[k]) for k in VALID_AIS]

    def _normalize_for_mode(self) -> None:
        """模式切换后的身份归一化，保证选项与模式语义一致。"""
        if self.mode == "human_vs_human":
            self.p1_ai = None
            self.p2_ai = None
        elif self.mode == "ai_vs_ai":
            self.p1_ai = self.p1_ai or "mcts"
            self.p2_ai = self.p2_ai or "random"
        else:  # human_vs_ai：保证恰好一方人类、一方 AI
            self._keep_human_vs_ai()

    def _keep_human_vs_ai(self, changed_key: Optional[str] = None) -> None:
        """
        人机大战联动：修正「双方皆人类」或「双方皆 AI」的冲突选择。

        冲突时「当前修改的一方」优先生效，另一方让位为人类；
        changed_key 为 None（如模式切换）时默认白方让位。
        """
        if self.p1_ai is None and self.p2_ai is None:
            self.p2_ai = "mcts"      # 双方皆人类：默认 AI 后手
        elif self.p1_ai is not None and self.p2_ai is not None:
            if changed_key == "p1_ai":
                self.p2_ai = None    # 黑方刚选 AI，白方让位为人类
            else:
                self.p1_ai = None    # 白方刚选 AI（或模式切换），黑方让位为人类

    # ===================== 布局与按钮构建 =====================

    def _build_layout(self) -> None:
        """根据当前选项状态重建所有按钮（切换选项后需刷新选中态）。"""
        self.buttons.clear()
        self._row_labels: List[Tuple[str, int]] = []
        cx = theme.S(self.cfg.window_width) // 2

        # ---- 第一组：棋种 ----
        self._option_row(
            y=theme.S(92), center_x=cx, label="棋种",
            options=[(g, self.GAME_LABELS[g]) for g in VALID_GAMES],
            current=self.game_kind,
            on_select=lambda v: self._set("game_kind", v),
        )

        # ---- 第二组：对局模式 ----
        self._option_row(
            y=theme.S(164), center_x=cx, label="模式",
            options=[(m, self.MODE_LABELS[m]) for m in VALID_MODES],
            current=self.mode,
            on_select=lambda v: self._set("mode", v),
        )

        # ---- 第三组：先手（黑方）身份与算法 ----
        self._option_row(
            y=theme.S(236), center_x=cx, label="黑方",
            options=self._player_options("p1"),
            current=self.p1_ai,
            on_select=lambda v: self._set("p1_ai", v),
        )

        # ---- 第四组：后手（白方）身份与算法 ----
        self._option_row(
            y=theme.S(308), center_x=cx, label="白方",
            options=self._player_options("p2"),
            current=self.p2_ai,
            on_select=lambda v: self._set("p2_ai", v),
        )

        # ---- 第五组：棋盘尺寸（随棋种可选范围刷新） ----
        sizes = GAME_DEFAULTS[self.game_kind]["allowed_sizes"]
        current_size = self.board_size or GAME_DEFAULTS[self.game_kind]["board_size"]
        self._option_row(
            y=theme.S(380), center_x=cx, label="棋盘",
            options=[(s, f"{s} 路") for s in sizes],
            current=current_size,
            on_select=lambda v: self._set("board_size", v),
        )

        # ---- 底部：开始对局主按钮 + 棋谱回放 + 大模型设置 ----
        start_rect = pygame.Rect(cx - theme.S(120), theme.S(500), theme.S(240), theme.S(52))
        self.buttons.append(Button(
            start_rect, "开始对局", on_click=self._start, accent=True,
            font_size=theme.FONT_HEAD,
        ))
        if self.on_replay is not None:
            replay_rect = pygame.Rect(cx - theme.S(100), theme.S(562),
                                      theme.S(200), theme.S(40))
            self.buttons.append(Button(
                replay_rect, "棋谱回放", on_click=self.on_replay,
                font_size=theme.FONT_BODY,
            ))
        if self.on_llm_settings is not None:
            llm_rect = pygame.Rect(cx + theme.S(110), theme.S(562),
                                   theme.S(200), theme.S(40))
            self.buttons.append(Button(
                llm_rect, "大模型设置", on_click=self.on_llm_settings,
                font_size=theme.FONT_BODY,
            ))

    def _option_row(self, y: int, center_x: int, label: str,
                    options: List[Tuple[object, str]], current,
                    on_select: Callable[[object], None]) -> None:
        """
        构建一行选项按钮：左侧组标题，右侧横向排列若干互斥选项按钮。
        """
        btn_w, btn_h, gap = theme.S(130), theme.S(40), theme.S(14)
        total_w = len(options) * btn_w + (len(options) - 1) * gap
        start_x = center_x - total_w // 2

        # 组标题放在按钮行左侧固定位置
        draw_text_y = y + theme.S(8)
        # 选项按钮
        for i, (value, text) in enumerate(options):
            rect = pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h)
            self.buttons.append(Button(
                rect, text,
                on_click=lambda v=value: on_select(v),
                selected=(value == current),
                font_size=theme.FONT_SMALL,
            ))

        # 保存组标题位置供 draw 阶段绘制
        self._row_labels.append((label, draw_text_y))

    def _set(self, attr: str, value) -> None:
        """更新选项状态并重建按钮（刷新选中高亮）；切换棋种时重置棋盘尺寸。"""
        setattr(self, attr, value)
        # 棋种切换后旧尺寸可能不在新棋种允许范围内，回退为新棋种默认尺寸
        if attr == "game_kind":
            self.board_size = None
        # 模式切换 / 身份修改时按模式联动归一化（人机大战保持一人一 AI）
        if attr == "mode":
            self._normalize_for_mode()
        elif attr in ("p1_ai", "p2_ai") and self.mode == "human_vs_ai":
            self._keep_human_vs_ai(changed_key=attr)
        self._build_layout()

    def _start(self) -> None:
        """把菜单选择打包后回调给 App。"""
        self.on_start({
            "game_kind": self.game_kind,
            "mode": self.mode,
            "p1_ai": self.p1_ai,
            "p2_ai": self.p2_ai,
            "board_size": self.board_size,
        })

    # ===================== 事件与绘制 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        """分发按钮点击事件。"""
        for btn in self.buttons:
            btn.handle_event(event)

    def update(self) -> None:
        """刷新按钮悬停态。"""
        mouse_pos = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.update(mouse_pos)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制背景、标题、各组标题、选项按钮与说明文字。"""
        surface.fill(theme.BG)
        cx = theme.S(self.cfg.window_width) // 2

        # 主标题
        draw_text(surface, "棋类综合对战平台", cx, theme.S(44),
                  size=theme.FONT_TITLE, color=theme.TEXT, align="center")
        draw_text(surface, "五子棋 · 黑白棋 ｜ 人机大战 ｜ 算法 PK ｜ 大模型对局",
                  cx, theme.S(76), size=theme.FONT_SMALL, color=theme.TEXT_LIGHT, align="center")

        # 绘制各组标题（与按钮行一一对应）
        label_x = theme.S(60)
        for label, y in self._row_labels:
            draw_text(surface, label, label_x, y,
                      size=theme.FONT_BODY, color=theme.TEXT)

        # 绘制按钮
        for btn in self.buttons:
            btn.draw(surface)

        # 底部操作提示
        draw_text(surface,
                  "提示：选择「大模型」需先在「大模型设置」中配置 API Key；"
                  "AI 思考过程会在对局界面实时可视化。",
                  cx, theme.S(624), size=theme.FONT_SMALL,
                  color=theme.TEXT_LIGHT, align="center")
