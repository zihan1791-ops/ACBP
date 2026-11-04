# -*- coding: utf-8 -*-
"""
棋谱回放场景（ReplayScene）。

功能：
1. 文件列表态：扫描 records 目录中的棋谱 JSON，展示每局的棋种 / 时间 /
   手数 / 结果摘要，点击进入回放；
2. 回放态：复用 BoardView 渲染棋盘，支持「上一步 / 下一步 / 自动播放 /
   返回列表 / 返回菜单」，侧栏展示双方角色与当前步数。

交互：
    ← / →     上一步 / 下一步
    空格       开始 / 暂停自动播放
    Esc        返回文件列表（回放态）或主菜单（列表态）
"""

import json
import os
from datetime import datetime
from typing import Callable, List, Optional, Tuple

import pygame

from . import theme
from .board_view import BoardView
from .widgets import Button, Panel, draw_text
from core.base_board import BLACK
from core.gomoku.board import GomokuBoard
from core.othello.board import OthelloBoard
from config import GAME_DEFAULTS
from utils.paths import resolve_path

# 每页展示的棋谱条数
_PAGE_SIZE = 7
# 自动播放每步间隔（毫秒）
_AUTO_INTERVAL_MS = 600


class ReplayScene:
    """棋谱回放：先选文件，再逐步复盘。"""

    def __init__(self, cfg, on_back: Callable[[], None],
                 on_resume: Optional[Callable[[dict, int], None]] = None) -> None:
        self.cfg = cfg
        self.on_back = on_back
        self.on_resume = on_resume

        w, h = theme.S(cfg.window_width), theme.S(cfg.window_height)
        self.w, self.h = w, h

        # ---- 回放态数据 ----
        self.record = None          # 当前棋谱原始 dict
        self.board = None           # 重建的规则棋盘
        self.moves: list = []       # 棋谱步列表（与 record["moves"] 一致）
        self.step = 0               # 当前已播放到的步数
        self.auto_play = False
        self._auto_elapsed = 0      # 自动播放累计毫秒

        # ---- 列表态数据 ----
        self.records: List[Tuple[str, dict]] = []   # (文件路径, 元信息)
        self.page = 0
        self.state = "list"         # "list" 文件列表 / "play" 回放 / "setup" 续局设置

        # ---- 续局角色选择（setup 态） ----
        self.setup_p1 = None        # None 人类；否则算法名
        self.setup_p2 = None

        self.buttons: List[Button] = []
        self.board_view = None
        self.panel: Optional[Panel] = None

        self._scan_records()
        self._build_list_buttons()

    # ===================== 列表态：棋谱扫描与构建 =====================

    def _scan_records(self) -> None:
        """递归扫描 records 目录（含日期子文件夹），按开始时间倒序读取摘要。"""
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
        # 按开始时间倒序：无时间的排在最后
        found.sort(key=lambda item: item[1]["started_at"], reverse=True)
        self.records = found

    def _build_list_buttons(self) -> None:
        """列表态布局：标题 + 当前页棋谱条目 + 翻页 / 返回按钮。"""
        self.buttons.clear()
        cx = self.w // 2

        # 当前页条目
        start = self.page * _PAGE_SIZE
        page_items = self.records[start:start + _PAGE_SIZE]
        for i, (path, meta) in enumerate(page_items):
            rect = pygame.Rect(theme.S(120), theme.S(120) + i * theme.S(60),
                               self.w - theme.S(240), theme.S(50))
            self.buttons.append(Button(
                rect, self._list_label(meta),
                on_click=lambda p=path: self._open_record(p),
                font_size=theme.FONT_BODY,
            ))

        # 翻页与返回
        if self.page > 0:
            self.buttons.append(Button(
                pygame.Rect(theme.S(120), self.h - theme.S(64), theme.S(120), theme.S(40)),
                "上一页", on_click=self._prev_page, font_size=theme.FONT_BODY))
        total_pages = max(1, (len(self.records) + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if self.page + 1 < total_pages:
            self.buttons.append(Button(
                pygame.Rect(self.w - theme.S(240), self.h - theme.S(64),
                            theme.S(120), theme.S(40)),
                "下一页", on_click=self._next_page, font_size=theme.FONT_BODY))
        self.buttons.append(Button(
            pygame.Rect(cx - theme.S(100), self.h - theme.S(64),
                        theme.S(200), theme.S(40)),
            "返回主菜单", on_click=self.on_back, accent=True,
            font_size=theme.FONT_BODY))

    @staticmethod
    def _list_label(meta: dict) -> str:
        """把棋谱元信息压缩为列表行文本（含开局日期）。"""
        name = GAME_DEFAULTS.get(meta["game"], {}).get("name", meta["game"])
        try:
            when = datetime.fromisoformat(meta["started_at"]).strftime("%y-%m-%d %H:%M")
        except (ValueError, TypeError):
            when = meta["started_at"][:16] if meta["started_at"] else "?"
        return f"{name}｜{when}｜{meta['moves']} 手｜{meta['result_text']}"

    def _prev_page(self) -> None:
        """上一页。"""
        if self.page > 0:
            self.page -= 1
            self._build_list_buttons()

    def _next_page(self) -> None:
        """下一页。"""
        if (self.page + 1) * _PAGE_SIZE < len(self.records):
            self.page += 1
            self._build_list_buttons()

    # ===================== 回放态：加载与播放 =====================

    def _open_record(self, path: str) -> None:
        """加载棋谱 JSON，重建棋盘与棋盘视图，进入回放态。"""
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

        # 按棋种与尺寸重建规则棋盘
        size = data.get("board_size") or GAME_DEFAULTS[data["game"]]["board_size"]
        if data.get("game") == "othello":
            self.board = OthelloBoard(size)
        else:
            self.board = GomokuBoard(size)

        # 棋盘视图区域（左侧大区，与对局场景一致）
        board_rect = (theme.PAD, theme.PAD, int(self.w * 0.66),
                      self.h - theme.PAD * 2)
        self.board_view = BoardView(board_rect, self.board)

        # 侧栏面板与按钮
        panel_x = int(self.w * 0.66) + theme.PAD * 2
        self.panel = Panel(pygame.Rect(panel_x, theme.PAD,
                                       self.w - panel_x - theme.PAD,
                                       self.h - theme.PAD * 2))
        self._build_play_buttons(panel_x, self.w - theme.PAD)

        self.state = "play"

    def _build_play_buttons(self, panel_x: int, right: int) -> None:
        """回放态按钮：自动播放 / 上一步 / 下一步 / 返回列表 / 返回菜单。"""
        self.buttons.clear()
        self._play_panel_x = panel_x
        self._play_right = right

        # 面板顶部：返回按钮
        self.buttons.append(Button(
            pygame.Rect(panel_x + theme.S(16), theme.PAD + theme.S(16),
                        right - panel_x - theme.S(32), theme.S(40)),
            "返回列表", on_click=self._show_list, font_size=theme.FONT_BODY))

        # 棋盘区下方居中：播放控制（上一步 / 播放暂停 / 下一步）
        y = self.h - theme.S(84)
        gap = theme.S(16)
        btn_w = theme.S(110)
        btn_h = theme.S(46)
        total_w = btn_w * 3 + gap * 2
        x0 = (self.w * 0.66) // 2 - total_w // 2 + theme.S(16)
        self.buttons.append(Button(
            pygame.Rect(x0, y, btn_w, btn_h), "上一步",
            on_click=self._prev_step, font_size=theme.FONT_BODY))
        self.buttons.append(Button(
            pygame.Rect(x0 + btn_w + gap, y, btn_w, btn_h),
            "自动播放" if not self.auto_play else "暂停",
            on_click=self._toggle_auto, accent=True, font_size=theme.FONT_BODY))
        self.buttons.append(Button(
            pygame.Rect(x0 + (btn_w + gap) * 2, y, btn_w, btn_h), "下一步",
            on_click=self._next_step, font_size=theme.FONT_BODY))

        # 侧栏底部：从当前局面继续对弈（回放到此继续玩）
        if self.on_resume is not None:
            self.buttons.append(Button(
                pygame.Rect(panel_x + theme.S(16), self.h - theme.S(116),
                            right - panel_x - theme.S(32), theme.S(40)),
                "从这继续对局", on_click=self._open_setup, accent=True,
                font_size=theme.FONT_BODY))

        # 侧栏底部：返回主菜单
        self.buttons.append(Button(
            pygame.Rect(panel_x + theme.S(16), self.h - theme.S(64),
                        right - panel_x - theme.S(32), theme.S(40)),
            "返回主菜单", on_click=self.on_back, accent=True,
            font_size=theme.FONT_BODY))

    # ===================== 续局设置态（选择 AI 介入） =====================

    ROLE_LABELS: dict = {None: "人类", "mcts": "MCTS", "alphabeta": "Alpha-Beta",
                         "random": "随机"}

    def _open_setup(self) -> None:
        """进入续局设置：可重新指定双方角色后从回放点继续对弈。"""
        self.state = "setup"
        players = self.record.get("players", {})
        black = players.get("black") or {}
        white = players.get("white") or {}
        self.setup_p1 = black.get("ai") if black.get("type") == "ai" else None
        self.setup_p2 = white.get("ai") if white.get("type") == "ai" else None
        self._build_setup_buttons()

    def _build_setup_buttons(self) -> None:
        """续局设置态布局：黑方/白方角色选项行 + 开始续局 / 返回回放。"""
        self.buttons.clear()
        cx = self.w // 2

        def option_row(y: int, label: str, current,
                       on_select) -> None:
            options = [(None, "人类"), ("mcts", "MCTS"),
                       ("alphabeta", "Alpha-Beta"), ("random", "随机")]
            btn_w, btn_h, gap = theme.S(130), theme.S(40), theme.S(14)
            total_w = len(options) * btn_w + (len(options) - 1) * gap
            start_x = cx - total_w // 2
            for i, (value, text) in enumerate(options):
                rect = pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h)
                self.buttons.append(Button(
                    rect, text, on_click=lambda v=value: on_select(v),
                    selected=(value == current), font_size=theme.FONT_SMALL))
            self._row_labels.append((label, y + theme.S(8)))

        self._row_labels = []
        option_row(theme.S(180), "黑方", self.setup_p1,
                   lambda v: self._set_setup("setup_p1", v))
        option_row(theme.S(260), "白方", self.setup_p2,
                   lambda v: self._set_setup("setup_p2", v))

        # 开始续局 + 返回回放
        self.buttons.append(Button(
            pygame.Rect(cx - theme.S(120), theme.S(400), theme.S(240), theme.S(52)),
            "开始续局", on_click=self._start_resume, accent=True,
            font_size=theme.FONT_HEAD))
        self.buttons.append(Button(
            pygame.Rect(cx - theme.S(100), theme.S(470), theme.S(200), theme.S(40)),
            "返回回放", on_click=self._back_to_play, font_size=theme.FONT_BODY))

    def _set_setup(self, attr: str, value) -> None:
        """更新续局角色选择并刷新高亮。"""
        setattr(self, attr, value)
        self._build_setup_buttons()

    def _start_resume(self) -> None:
        """确认角色选择，从回放点继续对局。"""
        if self.on_resume is not None:
            self.on_resume(self.record, self.step,
                           self.setup_p1, self.setup_p2)

    def _back_to_play(self) -> None:
        """从续局设置返回回放态（保留当前回放位置）。"""
        self.state = "play"
        self._build_play_buttons(self._play_panel_x, self._play_right)
        self._refresh_auto_button()

    def _show_list(self) -> None:
        """从回放态回到文件列表态。"""
        self.state = "list"
        self.record = None
        self.board = None
        self.board_view = None
        self.panel = None
        self._build_list_buttons()

    # ===================== 播放控制 =====================

    def _apply_upto(self, count: int) -> None:
        """重建棋盘并把前 count 步应用到棋盘（回放定位）。"""
        size = self.record.get("board_size") or GAME_DEFAULTS[self.record["game"]]["board_size"]
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
        """前进一手（不越过末尾）。"""
        if self.step < len(self.moves):
            self.step += 1
            self._apply_upto(self.step)

    def _prev_step(self) -> None:
        """后退一手。"""
        if self.step > 0:
            self.step -= 1
            self._apply_upto(self.step)

    def _toggle_auto(self) -> None:
        """开始 / 暂停自动播放；到末尾时自动停下。"""
        if self.step >= len(self.moves):
            self.step = 0
            self._apply_upto(0)
        self.auto_play = not self.auto_play
        self._auto_elapsed = 0
        self._refresh_auto_button()

    def _refresh_auto_button(self) -> None:
        """刷新自动播放按钮文字（播放/暂停切换）。"""
        for btn in self.buttons:
            if btn.text in ("自动播放", "暂停"):
                btn.text = "暂停" if self.auto_play else "自动播放"

    # ===================== 事件与更新 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        """分发按钮点击与键盘快捷键。"""
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
        """自动播放计时推进；刷新按钮悬停态。"""
        if self.state == "play" and self.auto_play:
            self._auto_elapsed += 16  # 主循环约 60 FPS，近似 16ms/帧
            if self._auto_elapsed >= _AUTO_INTERVAL_MS:
                self._auto_elapsed = 0
                if self.step < len(self.moves):
                    self._next_step()
                else:
                    self.auto_play = False
                    self._refresh_auto_button()

        mouse_pos = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.update(mouse_pos)

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface) -> None:
        """按当前状态绘制：文件列表 / 棋谱回放 / 续局设置。"""
        surface.fill(theme.BG)
        if self.state == "list":
            self._draw_list(surface)
        elif self.state == "setup":
            self._draw_setup(surface)
        else:
            self._draw_play(surface)

    def _draw_setup(self, surface: pygame.Surface) -> None:
        """续局设置态：标题 + 提示 + 双方角色选项行 + 操作按钮。"""
        cx = self.w // 2
        draw_text(surface, "续局设置", cx, theme.S(56),
                  size=theme.FONT_TITLE, color=theme.TEXT, align="center")
        draw_text(surface, f"将从第 {self.step} 手局面继续对弈，"
                           "可重新指定双方角色（选择 AI 即 AI 介入）",
                  cx, theme.S(100), size=theme.FONT_SMALL,
                  color=theme.TEXT_LIGHT, align="center")

        label_x = theme.S(60)
        for label, y in self._row_labels:
            draw_text(surface, label, label_x, y,
                      size=theme.FONT_BODY, color=theme.TEXT)

        for btn in self.buttons:
            btn.draw(surface)

    def _draw_list(self, surface: pygame.Surface) -> None:
        """列表态：标题 + 棋谱条目 + 底部按钮。"""
        cx = self.w // 2
        draw_text(surface, "棋谱回放", cx, theme.S(56),
                  size=theme.FONT_TITLE, color=theme.TEXT, align="center")
        if self.records:
            draw_text(surface, f"共 {len(self.records)} 局棋谱，点击条目开始回放",
                      cx, theme.S(88), size=theme.FONT_SMALL,
                      color=theme.TEXT_LIGHT, align="center")
        else:
            draw_text(surface, "暂无棋谱：先去下完一局（终局自动保存）再来回放吧",
                      cx, theme.S(200), size=theme.FONT_BODY,
                      color=theme.TEXT_LIGHT, align="center")

        for btn in self.buttons:
            btn.draw(surface)

    def _draw_play(self, surface: pygame.Surface) -> None:
        """回放态：棋盘 + 侧栏（角色 / 步数 / 当前手 / 结果）+ 控制按钮。"""
        if self.board_view is not None:
            self.board_view.draw(surface)

        if self.panel is not None:
            self.panel.draw(surface)
            self._draw_panel(surface)

        for btn in self.buttons:
            btn.draw(surface)

    def _draw_panel(self, surface: pygame.Surface) -> None:
        """绘制侧栏信息：棋局摘要、双方角色、步数与结果。"""
        panel = self.panel.rect
        data = self.record

        name = GAME_DEFAULTS.get(data["game"], {}).get("name", data["game"])
        draw_text(surface, f"{name} · {data.get('board_size')} 路 回放",
                  panel.x + theme.S(18), panel.y + theme.S(80),
                  size=theme.FONT_HEAD, color=theme.TEXT)

        # 双方角色
        players = data.get("players", {})
        draw_text(surface, "黑方：" + self._role_text(players.get("black")),
                  panel.x + theme.S(18), panel.y + theme.S(140),
                  size=theme.FONT_BODY, color=theme.TEXT)
        draw_text(surface, "白方：" + self._role_text(players.get("white")),
                  panel.x + theme.S(18), panel.y + theme.S(176),
                  size=theme.FONT_BODY, color=theme.TEXT)

        pygame.draw.line(surface, theme.PANEL_BORDER,
                         (panel.x + theme.S(18), panel.y + theme.S(220)),
                         (panel.right - theme.S(18), panel.y + theme.S(220)), 1)

        # 播放进度与当前手
        total = len(self.moves)
        draw_text(surface, f"步数：{self.step} / {total}",
                  panel.x + theme.S(18), panel.y + theme.S(250),
                  size=theme.FONT_BODY, color=theme.ACCENT_DARK)
        if 0 < self.step <= total:
            mv = self.moves[self.step - 1]
            who = "黑" if mv.get("player") == BLACK else "白"
            r, c = mv["move"]
            draw_text(surface, f"第 {self.step} 手：{who}方 ({r},{c})",
                      panel.x + theme.S(18), panel.y + theme.S(290),
                      size=theme.FONT_SMALL, color=theme.TEXT_LIGHT)

        # 终局结果
        if self.step >= total and total > 0:
            draw_text(surface, data.get("result_text", "对局结束"),
                      panel.x + theme.S(18), panel.y + theme.S(330),
                      size=theme.FONT_BODY, color=theme.WARN)

    @staticmethod
    def _role_text(role) -> str:
        """把棋谱中的角色信息转为中文描述。"""
        if not role:
            return "未知"
        if role.get("type") == "ai":
            return {"mcts": "MCTS", "alphabeta": "Alpha-Beta",
                    "random": "随机"}.get(role.get("ai"), role.get("ai"))
        return "人类"
