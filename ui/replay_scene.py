# -*- coding: utf-8 -*-
"""
棋谱回放场景（ReplayScene）—— 刊物的「棋谱档案」跨页（1440x900 基准）。

三个状态与全部数据契约保持不变：
    list  扫描 records/*.json（字段名一个都不改），分页目录
    play  重建 GomokuBoard / OthelloBoard，逐步 / 自动播放，棋谱栏复盘
    setup 选择双方角色后回调 on_resume(record, step, p1_ai, p2_ai)
快捷键 ← / → / 空格 / Esc 语义不变；另加 Tab + Enter 的键盘可达。

本轮调整：按 1440x900 重排，目录行高 52→64、行距 62→84，
复盘页棋谱活字列由 8 行扩到 10 行且字号 11→17；删除卷号、
栏目英文副名、副刊名与空态占位词，只留算法名 / 坐标 / 编号等数据标识。
"""

import json
import os
from datetime import datetime
from typing import Callable, List, Optional, Tuple

import pygame

from . import theme, motion, assets, atmosphere
from .board_view import BoardView
from .widgets import Button, Panel, blit_reveal, keyboard_nav
from core.base_board import BLACK
from core.gomoku.board import GomokuBoard
from core.othello.board import OthelloBoard
from config import GAME_DEFAULTS
from utils.paths import resolve_path

_PAGE_SIZE = 7
_AUTO_INTERVAL_MS = 600


class ReplayScene:
    """棋谱回放：先选文件，再逐步复盘。"""

    ROLE_LABELS: dict = {None: "人类", "mcts": "MCTS",
                         "alphabeta": "Alpha-Beta", "random": "随机"}

    def __init__(self, cfg, on_back: Callable[[], None],
                 on_resume: Optional[Callable[[dict, int], None]] = None) -> None:
        self.cfg = cfg
        self.on_back = on_back
        self.on_resume = on_resume

        self.w, self.h = theme.window_size(cfg)
        self.s = theme.S
        self.born = motion.now()
        self.kb_index = 0
        self.kb_mode = False

        self.record = None
        self.board = None
        self.moves: list = []
        self.step = 0
        self.auto_play = False
        self._auto_elapsed = 0

        self.records: List[Tuple[str, dict]] = []
        self.page = 0
        self.state = "list"

        self.setup_p1 = None
        self.setup_p2 = None
        self._row_labels: List[Tuple[str, int, int]] = []

        self.buttons: List[Button] = []
        self.board_view = None
        self.panel: Optional[Panel] = None
        self._play_panel_x = 0
        self._play_right = 0

        self._scan_records()
        self._build_list_buttons()

    # ===================== 列表态：棋谱扫描与目录 =====================

    def _scan_records(self) -> None:
        record_root = resolve_path(getattr(self.cfg, "records_dir", "records"))
        found: List[Tuple[str, dict]] = []
        for root, _dirs, files in os.walk(record_root):
            for name in files:
                if not name.lower().endswith(".json"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    continue
                found.append((path, {
                    "game": data.get("game", "?"),
                    "started_at": data.get("started_at", ""),
                    "result_text": data.get("result_text", ""),
                    "moves": len(data.get("moves", [])),
                }))
        found.sort(key=lambda item: item[1]["started_at"], reverse=True)
        self.records = found

    def _build_list_buttons(self) -> None:
        s = self.s
        self.buttons.clear()
        start = self.page * _PAGE_SIZE
        page_items = self.records[start:start + _PAGE_SIZE]
        for i, (path, meta) in enumerate(page_items):
            rect = pygame.Rect(s(430), s(160) + i * s(84), s(950), s(64))
            btn = Button(rect, self._list_label(meta),
                         on_click=lambda p=path: self._open_record(p),
                         font_size=theme.FONT_BODY, flat=True,
                         prefix="%02d" % (start + i + 1))
            btn.reveal_delay = 100 + i * theme.MOTION["stagger"]
            self.buttons.append(btn)

        specs = []
        if self.page > 0:
            specs.append((s(430), s(180), "上一页", self._prev_page, False))
        total_pages = max(1, (len(self.records) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if self.page + 1 < total_pages:
            specs.append((s(626), s(180), "下一页", self._next_page, False))
        specs.append((s(1140), s(240), "返回主菜单", self.on_back, True))
        for i, (x, width, text, cb, accent) in enumerate(specs):
            btn = Button((x, s(780), width, s(60)), text, on_click=cb,
                         font_size=theme.FONT_BODY, accent=accent)
            btn.reveal_delay = 520 + i * theme.MOTION["stagger"]
            self.buttons.append(btn)

        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))

    @staticmethod
    def _list_label(meta: dict) -> str:
        name = GAME_DEFAULTS.get(meta["game"], {}).get("name", meta["game"])
        try:
            when = datetime.fromisoformat(meta["started_at"]).strftime("%y-%m-%d %H:%M")
        except (ValueError, TypeError):
            when = meta["started_at"][:16] if meta["started_at"] else "?"
        result = str(meta.get("result_text", "")).replace("对局结束：", "")
        return "%s    %s    %02d 手    %s" % (name, when, meta["moves"], result)

    def _prev_page(self) -> None:
        if self.page > 0:
            self.page -= 1
            self.born = motion.now()
            self._build_list_buttons()

    def _next_page(self) -> None:
        if (self.page + 1) * _PAGE_SIZE < len(self.records):
            self.page += 1
            self.born = motion.now()
            self._build_list_buttons()

    # ===================== 回放态：加载与播放 =====================

    def _open_record(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self._show_list()
            return
        if "moves" not in data:
            self._show_list()
            return

        self.record = data
        self.moves = data.get("moves", [])
        self.step = 0
        self.auto_play = False
        self._auto_elapsed = 0
        self.born = motion.now()

        size = data.get("board_size") or GAME_DEFAULTS[data["game"]]["board_size"]
        if data.get("game") == "othello":
            self.board = OthelloBoard(size)
        else:
            self.board = GomokuBoard(size)

        s = self.s
        self.board_view = BoardView((s(36), s(96), s(800), s(690)), self.board)
        panel_x = s(864)
        self.panel = Panel(pygame.Rect(panel_x, s(96), s(540), s(752)))
        self._build_play_buttons(panel_x, s(1404))
        self.state = "play"

    def _build_play_buttons(self, panel_x: int, right: int) -> None:
        """棋盘下方 4 枚控制键 + 右栏底部 2 枚导航键。"""
        s = self.s
        self.buttons.clear()
        self._play_panel_x = panel_x
        self._play_right = right

        control = [
            (s(36), s(190), "上一步", self._prev_step, False),
            (s(238), s(190), "自动播放" if not self.auto_play else "暂停",
             self._toggle_auto, True),
            (s(440), s(190), "下一步", self._next_step, False),
            (s(642), s(194), "返回主菜单", self.on_back, False),
        ]
        for i, (x, width, text, cb, accent) in enumerate(control):
            btn = Button((x, s(800), width, s(48)), text, on_click=cb,
                         font_size=theme.FONT_BODY, accent=accent)
            btn.reveal_delay = 200 + i * theme.MOTION["stagger"]
            self.buttons.append(btn)

        nav = [(s(716), "返回列表", self._show_list, False)]
        if self.on_resume is not None:
            nav.append((s(776), "从这继续对局", self._open_setup, True))
        for i, (y, text, cb, accent) in enumerate(nav):
            btn = Button((panel_x + s(24), y, s(540) - s(48), s(48)),
                         text, on_click=cb, font_size=theme.FONT_BODY,
                         accent=accent)
            btn.reveal_delay = 320 + i * theme.MOTION["stagger"]
            self.buttons.append(btn)

        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))

    # ===================== 续局设置态 =====================

    def _open_setup(self) -> None:
        self.state = "setup"
        self.born = motion.now()
        players = self.record.get("players", {})
        black = players.get("black") or {}
        white = players.get("white") or {}
        self.setup_p1 = black.get("ai") if black.get("type") == "ai" else None
        self.setup_p2 = white.get("ai") if white.get("type") == "ai" else None
        self._build_setup_buttons()

    def _build_setup_buttons(self) -> None:
        s = self.s
        self.buttons.clear()
        self._row_labels = []

        def option_row(y: int, label: str, current, on_select, row_no: int) -> None:
            options = [(None, "人类"), ("mcts", "MCTS"),
                       ("alphabeta", "Alpha-Beta"), ("random", "随机")]
            btn_w, btn_h, gap = s(150), s(52), s(12)
            total_w = len(options) * btn_w + (len(options) - 1) * gap
            start_x = s(1380) - total_w
            for i, (value, text) in enumerate(options):
                rect = pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h)
                btn = Button(rect, text,
                             on_click=lambda v=value: on_select(v),
                             selected=(value == current),
                             font_size=theme.FONT_BODY)
                btn.reveal_delay = 100 + row_no * theme.MOTION["stagger"]
                self.buttons.append(btn)
            self._row_labels.append((label, y, row_no))

        option_row(s(220), "黑方 · 先手", self.setup_p1,
                   lambda v: self._set_setup("setup_p1", v), 1)
        option_row(s(340), "白方 · 后手", self.setup_p2,
                   lambda v: self._set_setup("setup_p2", v), 2)

        for i, (x, width, text, cb, accent) in enumerate((
                (s(744), s(280), "开始续局", self._start_resume, True),
                (s(1040), s(240), "返回回放", self._back_to_play, False))):
            btn = Button((x, s(560), width, s(60)), text, on_click=cb,
                         font_size=theme.FONT_BODY, accent=accent)
            btn.reveal_delay = 320 + i * theme.MOTION["stagger"]
            self.buttons.append(btn)

        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))

    def _set_setup(self, attr: str, value) -> None:
        setattr(self, attr, value)
        self._build_setup_buttons()

    def _start_resume(self) -> None:
        if self.on_resume is not None:
            self.on_resume(self.record, self.step,
                           self.setup_p1, self.setup_p2)

    def _back_to_play(self) -> None:
        self.state = "play"
        self.born = motion.now()
        self._build_play_buttons(self._play_panel_x, self._play_right)
        self._refresh_auto_button()

    def _show_list(self) -> None:
        self.state = "list"
        self.born = motion.now()
        self.record = None
        self.board = None
        self.board_view = None
        self.panel = None
        self._build_list_buttons()

    # ===================== 播放控制 =====================

    def _apply_upto(self, count: int) -> None:
        size = self.record.get("board_size") or \
            GAME_DEFAULTS[self.record["game"]]["board_size"]
        if self.record.get("game") == "othello":
            self.board = OthelloBoard(size)
        else:
            self.board = GomokuBoard(size)
        for mv in self.moves[:count]:
            self.board.apply_move(tuple(mv["move"]))
        if self.board_view is not None:
            self.board_view.board = self.board
            self.board_view._layout()

    def _next_step(self) -> None:
        if self.step < len(self.moves):
            self.step += 1
            self._apply_upto(self.step)

    def _prev_step(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._apply_upto(self.step)

    def _toggle_auto(self) -> None:
        if self.step >= len(self.moves):
            self.step = 0
            self._apply_upto(0)
        self.auto_play = not self.auto_play
        self._auto_elapsed = 0
        self._refresh_auto_button()

    def _refresh_auto_button(self) -> None:
        for btn in self.buttons:
            if btn.text in ("自动播放", "暂停"):
                btn.text = "暂停" if self.auto_play else "自动播放"

    # ===================== 事件与更新 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            self.kb_mode = False
        elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_TAB, pygame.K_RETURN, pygame.K_KP_ENTER):
            self.kb_mode = True
            self.kb_index = keyboard_nav(self.buttons, event, self.kb_index,
                                         use_arrows=False)
            self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))
            return

        for btn in self.buttons:
            if btn.handle_event(event):
                return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                if self.state == "play":
                    self._prev_step()
            elif event.key == pygame.K_RIGHT:
                if self.state == "play":
                    self._next_step()
            elif event.key == pygame.K_SPACE:
                if self.state == "play":
                    self._toggle_auto()
            elif event.key == pygame.K_ESCAPE:
                if self.state == "play":
                    self._show_list()
                elif self.state == "setup":
                    self._back_to_play()
                else:
                    self.on_back()

    def update(self) -> None:
        if self.state == "play" and self.auto_play:
            self._auto_elapsed += 16
            if self._auto_elapsed >= _AUTO_INTERVAL_MS:
                self._auto_elapsed = 0
                if self.step < len(self.moves):
                    self._next_step()
                else:
                    self.auto_play = False
                    self._refresh_auto_button()

        mouse_pos = pygame.mouse.get_pos()
        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))
        for i, btn in enumerate(self.buttons):
            btn.update(mouse_pos)
            btn.focused = self.kb_mode and i == self.kb_index

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface) -> None:
        s = self.s
        surface.blit(atmosphere.paper(self.w, self.h), (0, 0))
        if self.state == "list":
            atmosphere.masthead(surface, self.w, "棋谱目录")
            self._draw_list(surface)
        elif self.state == "setup":
            atmosphere.masthead(surface, self.w, "续局设置")
            self._draw_setup(surface)
        else:
            atmosphere.masthead(surface, self.w, "棋谱复盘")
            self._draw_play(surface)

        for btn in self.buttons:
            btn.reveal = motion.reveal(self.born,
                                       getattr(btn, "reveal_delay", 0),
                                       theme.MOTION["base"])
            btn.draw(surface)

        pygame.draw.line(surface, theme.RULE_LIGHT,
                         (s(36), s(856)), (self.w - s(36), s(856)))
        keys = assets.mixed(s(15), "Tab 选择 · Enter 确认 · ← → 逐手 · 空格 播放 · Esc 返回",
                            theme.INK_SOFT)
        surface.blit(keys, (s(36), s(866)))

    def _draw_side_title(self, surface: pygame.Surface, zh: str,
                         lines: List[str]) -> None:
        """左栏：竖排宋体刊名 + 朱砂竖线 + 少量有信息量的说明。"""
        s = self.s
        vt = assets.vertical("display", s(44), zh, theme.INK, s(8))
        p = motion.reveal(self.born, 60, theme.MOTION["base"])
        blit_reveal(surface, vt, (s(72), s(130)), p, 20)
        if p > 0.2:
            pygame.draw.line(surface, theme.CINNABAR,
                             (s(56), s(130)),
                             (s(56), s(130) + int(vt.get_height() * p)), 3)
        for i, text in enumerate(lines):
            glyph = assets.mixed(s(17), text, theme.INK_SOFT)
            blit_reveal(surface, glyph, (s(56), s(560) + i * s(32)),
                        motion.reveal(self.born, 160 + i * 80,
                                      theme.MOTION["base"]), 14)

    def _draw_list(self, surface: pygame.Surface) -> None:
        s = self.s
        total = len(self.records)
        pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._draw_side_title(surface, "棋谱目录",
                              ["共 %d 局" % total,
                               "第 %d / %d 页" % (self.page + 1, pages)])
        atmosphere.section_label(surface, "索引", s(430), s(100))
        if not self.records:
            surface.blit(assets.mixed(s(19), "暂无棋谱", theme.INK_SOFT),
                         (s(470), s(200)))
            surface.blit(assets.mixed(s(17), "下完一局后会自动保存",
                                      theme.INK_SOFT),
                         (s(470), s(240)))

    def _draw_setup(self, surface: pygame.Surface) -> None:
        s = self.s
        self._draw_side_title(surface, "续局设置",
                              ["从第 %d 手继续" % self.step,
                               "选择算法即由该算法介入"])
        atmosphere.section_label(surface, "双方角色", s(430), s(130))
        for label, y, row_no in self._row_labels:
            p = motion.reveal(self.born, 100 + row_no * theme.MOTION["stagger"],
                              theme.MOTION["base"])
            no = assets.font("mono", s(14)).render("%02d" % row_no, True,
                                                   theme.CINNABAR)
            blit_reveal(surface, no, (s(430), y + s(10)), p, 12)
            lab = assets.font("body", s(20), True).render(label, True,
                                                          theme.INK)
            blit_reveal(surface, lab, (s(466), y + s(6)), p, 16)
            pygame.draw.line(surface, theme.RULE_LIGHT,
                             (s(430), y + s(72)), (s(1380), y + s(72)))

    def _draw_play(self, surface: pygame.Surface) -> None:
        if self.board_view is not None:
            self.board_view.draw(surface)
        if self.panel is not None:
            self.panel.draw(surface)
            self._draw_panel(surface)

    def _draw_panel(self, surface: pygame.Surface) -> None:
        """右栏：棋局摘要 + 双方角色 + 步数 + 10 行棋谱活字列。"""
        s = self.s
        panel = self.panel.rect
        x, top = panel.x + s(24), panel.y
        data = self.record
        name = GAME_DEFAULTS.get(data["game"], {}).get("name", data["game"])

        head = assets.font("display", s(34)).render(
            "%s · %s 路" % (name, data.get("board_size")), True, theme.INK)
        surface.blit(head, (x, top + s(10)))
        total = len(self.moves)
        step = assets.mixed(s(22), "第 %d / %d 手" % (self.step, total),
                            theme.CINNABAR)
        surface.blit(step, (x, top + s(52)))
        atmosphere.hairline(surface, (x, top + s(88)),
                            (panel.right - s(24), top + s(88)))

        players = data.get("players", {})
        for i, (side, key) in enumerate((("黑方", "black"), ("白方", "white"))):
            text = "%s：%s" % (side, self._role_text(players.get(key)))
            surface.blit(assets.mixed(s(18), text, theme.INK),
                         (x, top + s(100) + i * s(34)))

        atmosphere.hairline(surface, (x, top + s(158)),
                            (panel.right - s(24), top + s(158)))
        if 0 < self.step <= total:
            mv = self.moves[self.step - 1]
            who = "黑" if mv.get("player") == BLACK else "白"
            current = assets.mixed(s(17), "%s方  %s" %
                                   (who, self._fmt_coord(mv["move"])),
                                   theme.INK_SOFT)
            surface.blit(current, (x, top + s(168)))
        if self.step >= total and total > 0:
            surface.blit(assets.mixed(s(17), data.get("result_text", "对局结束"),
                                      theme.CINNABAR),
                         (x, top + s(196)))

        atmosphere.hairline(surface, (x, top + s(220)),
                            (panel.right - s(24), top + s(220)))
        label = assets.font("body", s(17), True).render("棋谱", True, theme.INK)
        surface.blit(label, (x + s(14), top + s(232)))
        pygame.draw.line(surface, theme.CINNABAR,
                         (x, top + s(236)), (x, top + s(254)), 3)
        self._draw_move_column(surface, x, top + s(270))

    def _draw_move_column(self, surface: pygame.Surface, x: int, y: int) -> None:
        """棋谱活字列：当前手附近 10 手，当前手朱砂 + 左侧短竖线。"""
        s = self.s
        rows = 10
        total = len(self.moves)
        first = max(0, min(self.step - 6, max(0, total - rows)))
        shown = self.moves[first:first + rows]
        atmosphere.column_rule(surface, x, y, y + s(34 * rows))
        for i, mv in enumerate(shown):
            no = first + i + 1
            who = "黑" if mv.get("player") == BLACK else "白"
            coord = self._fmt_coord(mv.get("move"))
            line = "%03d   %s   %-4s" % (no, who, coord)
            current = no == self.step
            glyph = assets.mixed(s(17), line,
                                 theme.CINNABAR if current else theme.INK_SOFT)
            surface.blit(glyph, (x + s(14), y + i * s(34)))
            if current:
                pygame.draw.line(surface, theme.CINNABAR,
                                 (x - s(2), y + i * s(34)),
                                 (x - s(2), y + i * s(34) + s(20)), 3)
        if not shown:
            surface.blit(assets.mixed(s(17), "尚无落子", theme.INK_SOFT),
                         (x + s(14), y))

    def _fmt_coord(self, move) -> str:
        if not move:
            return "—"
        size = (self.record.get("board_size") if self.record else None) \
            or (self.board.size if self.board else 15)
        col = chr(65 + move[1]) if move[1] < 26 else str(move[1])
        return "%s%d" % (col, size - move[0])

    @staticmethod
    def _role_text(role) -> str:
        if not role:
            return "未知"
        if role.get("type") == "ai":
            return {"mcts": "MCTS", "alphabeta": "Alpha-Beta",
                    "random": "随机"}.get(role.get("ai"), role.get("ai"))
        return "人类"
