# -*- coding: utf-8 -*-
"""
主菜单场景 —— 刊物的「开局设定」跨页（1440x900 基准）。

功能与联动逻辑保持原样（与配置层的契约）：
    棋种 / 模式 / 黑方 / 白方 / 棋盘尺寸 五组互斥选项；
    人机大战保证恰好一人一 AI，切换棋种重置尺寸；
    「开始对局」把 5 个键的 dict 交给 App。

本轮调整：版面按 1440x900 重排，行距 72→116、字号整体上调、
点击目标 42→52；删除破格刊号、栏目英文副名与副刊名等装饰文案，
只在左栏保留「当前设定」摘要这类有信息量的内容；模式切换给出一行
简短反馈，解释为什么双方身份被自动归一化。

外观入口：右下新增「外观设置」按钮（回调由 App 注入）；App 会在离开
主菜单前保存 current_options() 快照，返回时用 initial_options 恢复。
"""

from typing import Callable, Optional, Dict, List, Tuple

import pygame

from . import theme, motion, assets, atmosphere
from .widgets import Button, blit_reveal, keyboard_nav
from config import GAME_DEFAULTS, VALID_GAMES, VALID_MODES, VALID_AIS


class MainMenu:
    """开局主菜单界面。"""

    GAME_LABELS: Dict[str, str] = {"gomoku": "五子棋", "othello": "黑白棋"}
    MODE_LABELS: Dict[str, str] = {
        "human_vs_ai": "人机大战",
        "ai_vs_ai": "算法 PK",
        "human_vs_human": "人人对战",
    }
    AI_LABELS: Dict[Optional[str], str] = {
        None: "人类", "mcts": "MCTS", "alphabeta": "Alpha-Beta",
        "random": "随机",
    }

    def __init__(self, cfg, on_start: Callable[[dict], None],
                 on_replay: Optional[Callable[[], None]] = None,
                 on_settings: Optional[Callable[[], None]] = None,
                 initial_options: Optional[dict] = None) -> None:
        self.cfg = cfg
        self.on_start = on_start
        self.on_replay = on_replay
        self.on_settings = on_settings

        # 从设置页 / 对局返回时恢复上次开局设定；未指定则沿用 cfg 默认值
        opts = initial_options or {}
        self.game_kind: str = opts.get("game_kind", cfg.game or "gomoku")
        self.mode: str = opts.get("mode", cfg.mode or "human_vs_ai")
        self.p1_ai: Optional[str] = opts.get("p1_ai", cfg.p1_ai)
        self.p2_ai: Optional[str] = opts.get("p2_ai", cfg.p2_ai)
        self.board_size: Optional[int] = opts.get("board_size", cfg.board_size)

        self.buttons: List[Button] = []
        self._rows: List[dict] = []
        self.notice = ""
        self.kb_index = 0
        self.kb_mode = False
        self.born = motion.now()

        self._normalize_for_mode()
        self._build_layout()

    # ===================== 模式与身份联动（契约，逻辑不变） =====================

    def _player_options(self, key: str) -> List[Tuple[Optional[str], str]]:
        if self.mode == "human_vs_human":
            return [(None, self.AI_LABELS[None])]
        if self.mode == "ai_vs_ai":
            return [(k, self.AI_LABELS[k]) for k in VALID_AIS]
        return [(None, self.AI_LABELS[None])] + \
            [(k, self.AI_LABELS[k]) for k in VALID_AIS]

    def _normalize_for_mode(self) -> None:
        if self.mode == "human_vs_human":
            self.p1_ai = None
            self.p2_ai = None
        elif self.mode == "ai_vs_ai":
            self.p1_ai = self.p1_ai or "mcts"
            self.p2_ai = self.p2_ai or "random"
        else:
            self._keep_human_vs_ai()

    def _keep_human_vs_ai(self, changed_key: Optional[str] = None) -> None:
        if self.p1_ai is None and self.p2_ai is None:
            self.p2_ai = "mcts"
        elif self.p1_ai is not None and self.p2_ai is not None:
            if changed_key == "p1_ai":
                self.p2_ai = None
            else:
                self.p1_ai = None

    # ===================== 布局 =====================

    def _build_layout(self) -> None:
        s = theme.S
        self.buttons.clear()
        self._rows = []

        sizes = GAME_DEFAULTS[self.game_kind]["allowed_sizes"]
        current_size = self.board_size or GAME_DEFAULTS[self.game_kind]["board_size"]
        specs = [
            (s(160), "棋种",
             [(g, self.GAME_LABELS[g]) for g in VALID_GAMES], self.game_kind,
             lambda v: self._set("game_kind", v)),
            (s(276), "对局模式",
             [(m, self.MODE_LABELS[m]) for m in VALID_MODES], self.mode,
             lambda v: self._set("mode", v)),
            (s(392), "黑方 · 先手",
             self._player_options("p1"), self.p1_ai,
             lambda v: self._set("p1_ai", v)),
            (s(508), "白方 · 后手",
             self._player_options("p2"), self.p2_ai,
             lambda v: self._set("p2_ai", v)),
            (s(624), "棋盘路数",
             [(v, "%s 路" % v) for v in sizes], current_size,
             lambda v: self._set("board_size", v)),
        ]
        for i, (y, label, options, current, on_select) in enumerate(specs):
            self._option_row(y, 0, label, options, current, on_select,
                             row_no=i + 1)

        if self.on_settings is not None:
            settings = Button((s(360), s(780), s(240), s(60)), "外观设置",
                              on_click=self.on_settings,
                              font_size=theme.FONT_BODY)
            settings.reveal_delay = 470
            self.buttons.append(settings)

        start = Button((s(744), s(780), s(280), s(60)), "开始对局",
                       on_click=self._start, accent=True,
                       font_size=theme.FONT_HEAD)
        start.reveal_delay = 520
        self.buttons.append(start)
        if self.on_replay is not None:
            replay = Button((s(1040), s(780), s(240), s(60)), "棋谱回放",
                            on_click=self.on_replay,
                            font_size=theme.FONT_BODY)
            replay.reveal_delay = 580
            self.buttons.append(replay)

        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))

    def _option_row(self, y: int, center_x: int, label: str,
                    options: List[Tuple[object, str]], current,
                    on_select: Callable[[object], None],
                    row_no: int = 1) -> None:
        """一行选项：左侧行号 + 中文标签，右侧按钮组统一右对齐。"""
        s = theme.S
        btn_w, btn_h, gap = s(150), s(52), s(12)
        total_w = len(options) * btn_w + (len(options) - 1) * gap
        start_x = s(1380) - total_w
        for i, (value, text) in enumerate(options):
            rect = pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h)
            btn = Button(rect, text, on_click=lambda v=value: on_select(v),
                         selected=(value == current),
                         font_size=theme.FONT_BODY)
            btn.reveal_delay = 100 + row_no * theme.MOTION["stagger"]
            self.buttons.append(btn)
        self._rows.append({
            "no": "%02d" % row_no, "label": label,
            "y": y, "x": s(430), "line_y": y + s(72),
            "delay": 100 + row_no * theme.MOTION["stagger"],
        })

    def _set(self, attr: str, value) -> None:
        """更新选项并重建按钮；同时给出一行有信息量的联动反馈。"""
        setattr(self, attr, value)
        if attr == "game_kind":
            self.board_size = None
            self.notice = ""
        elif attr == "mode":
            self._normalize_for_mode()
            self.notice = "已按「%s」重置双方身份" % self.MODE_LABELS[self.mode]
        elif attr in ("p1_ai", "p2_ai") and self.mode == "human_vs_ai":
            self._keep_human_vs_ai(changed_key=attr)
            self.notice = "人机大战需一人一 AI，已自动调整另一方"
        else:
            self.notice = ""
        self._build_layout()

    def current_options(self) -> dict:
        """当前开局设定的快照（dict 的 5 个键是硬契约）。"""
        return {
            "game_kind": self.game_kind,
            "mode": self.mode,
            "p1_ai": self.p1_ai,
            "p2_ai": self.p2_ai,
            "board_size": self.board_size,
        }

    def _start(self) -> None:
        """把菜单选择打包后回调给 App。"""
        self.on_start(self.current_options())

    # ===================== 事件与更新 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            self.kb_mode = False
        elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_TAB, pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT,
                pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER,
                pygame.K_SPACE):
            self.kb_mode = True
            self.kb_index = keyboard_nav(self.buttons, event, self.kb_index)
            self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))
            return
        for btn in self.buttons:
            btn.handle_event(event)

    def update(self) -> None:
        mouse_pos = pygame.mouse.get_pos()
        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))
        for i, btn in enumerate(self.buttons):
            btn.update(mouse_pos)
            btn.focused = self.kb_mode and i == self.kb_index

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface) -> None:
        s = theme.S
        w, h = theme.window_size(self.cfg)
        surface.blit(atmosphere.paper(w, h), (0, 0))
        atmosphere.masthead(surface, w, "开局设定")

        # 左栏：竖排宋体刊名 + 朱砂竖线，无装饰副刊名
        pv = motion.reveal(self.born, 60, theme.MOTION["base"])
        vt = assets.vertical("display", s(44), "棋类综合对战平台",
                             theme.INK, s(8))
        blit_reveal(surface, vt, (s(72), s(130)), pv, 20)
        if pv > 0.2:
            pygame.draw.line(surface, theme.CINNABAR,
                             (s(56), s(130)),
                             (s(56), s(130) + int(vt.get_height() * pv)), 3)

        # 左栏底部：当前设定摘要（有信息量的内容，不是装饰文案）
        size_now = self.board_size or GAME_DEFAULTS[self.game_kind]["board_size"]
        summary = [
            ("当前设定", theme.INK),
            (self.GAME_LABELS[self.game_kind], theme.INK_SOFT),
            (self.MODE_LABELS[self.mode], theme.INK_SOFT),
            ("%s 路 · %s / %s" % (size_now,
                                  self.AI_LABELS[self.p1_ai],
                                  self.AI_LABELS[self.p2_ai]), theme.INK_SOFT),
        ]
        pygame.draw.line(surface, theme.RULE_LIGHT,
                         (s(56), s(652)), (s(160), s(652)))
        for i, (text, color) in enumerate(summary):
            glyph = assets.mixed(s(17), text, color)
            blit_reveal(surface, glyph, (s(56), s(670) + i * s(30)),
                        motion.reveal(self.born, 200 + i * 60,
                                      theme.MOTION["base"]), 14)

        # 右栏：栏目标签 + 五行设定表
        atmosphere.section_label(surface, "本局设定", s(430), s(100))
        for row in self._rows:
            p = motion.reveal(self.born, row["delay"], theme.MOTION["base"])
            no = assets.font("mono", s(14)).render(row["no"], True,
                                                   theme.CINNABAR)
            blit_reveal(surface, no, (row["x"], row["y"] + s(8)), p, 12)
            lab = assets.font("body", s(20), True).render(row["label"], True,
                                                          theme.INK)
            blit_reveal(surface, lab, (row["x"] + s(36), row["y"] + s(4)),
                        p, 16)
            rule_color = theme.blend(theme.RULE_LIGHT, theme.PAPER, 1.0 - p)
            pygame.draw.line(surface, rule_color,
                             (row["x"], row["line_y"]),
                             (s(1380), row["line_y"]))

        # 联动反馈（仅在身份被自动调整时出现）
        if self.notice:
            note = assets.mixed(s(17), self.notice, theme.CINNABAR)
            surface.blit(note, (s(744), s(720)))

        for btn in self.buttons:
            btn.reveal = motion.reveal(
                self.born, getattr(btn, "reveal_delay", 0),
                theme.MOTION["base"])
            btn.draw(surface)

        # 页脚：只保留一行键位提示
        pf = motion.reveal(self.born, 560, theme.MOTION["base"])
        pygame.draw.line(surface, theme.RULE_LIGHT,
                         (s(36), s(856)), (w - s(36), s(856)))
        keys = assets.mixed(s(15), "Tab 选择 · Enter 确认 · R 关闭动效",
                            theme.INK_SOFT)
        blit_reveal(surface, keys, (s(36), s(866)), pf, 8)
