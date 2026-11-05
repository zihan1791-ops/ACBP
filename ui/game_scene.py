# -*- coding: utf-8 -*-
"""
对局场景（GameScene）—— 刊物的「实战跨页」（1440x900 基准）。

与对局层的契约全部保持不变：
    BoardView 坐标换算、ctrl.handle_human_move / step_ai(on_progress) /
    undo / restart / status_text / score_text / result_text / players /
    current_player.ai / ThinkState 字段 / core.base_board.BLACK,WHITE。
    _on_ai_progress 仍在回调里主动 draw + flip（AI 与界面同线程）。

本轮解决「AI PK 时演算区反复跳动 / 人人对战时演算区无用」：
1. 布局彻底固定（LAYOUT 常量），不再随 think.active 切换区块高度；
2. 演算面板不再绑定「当前思考方」，改为按本局 AI 数量分三种呈现：
   人人对战 → 演算与候选整块隐藏，棋谱扩到 15 手；
   人机大战 → 单栏，人类回合保留该 AI 上一手的最终结论；
   算法 PK  → 双栏对照，两位 AI 各自保留自己的数据，当前思考方点亮；
3. 候选固定 3 个槽位并缓存，落子才清空；进度条保留上一步终值，
   棋盘候选标记不再每帧闪烁。

多进程模式（真实窗口默认启用）：搜索交给 ui/ai_runner.py 的长驻 worker，
主进程保持 60fps 事件循环；进度经队列回写 ThinkState，UI 渲染代码完全不变。
无头 / 测试环境（SDL_VIDEODRIVER=dummy）默认同步以保持既有测试语义，
可用 ACBP_AI_MODE=async|sync 显式覆盖；worker 异常会自动回退同步。
"""

import time
from typing import Callable, List

import pygame

from . import theme, motion, assets, atmosphere, ai_runner
from .board_view import BoardView
from .widgets import Button, Panel, keyboard_nav
from core.base_board import BLACK, WHITE
from config import GAME_DEFAULTS


class GameScene:
    """单局对局的交互与渲染场景。"""

    # 固定版面：所有数值为相对面板顶部的基准逻辑像素，任何模式、任何
    # 思考状态都不改变。这是消除 AI PK 布局跳动的关键。
    LAYOUT = {
        "state_line": 88,
        "identity": [100, 130],
        "info_line": 158,
        "info": 168,
        # 有 AI：演算 + 候选 + 棋谱
        "think_line": 196,
        "think_label": 208,
        "think_body": 240,
        "cand_line": 442,
        "cand_label": 454,
        "cand_rows": 486,
        "log_line": 584,
        "log_label": 596,
        "log_rows": 628,
        "log_step": 30,
        "log_count": 4,
        # 无 AI：演算/候选隐藏，棋谱独占
        "solo_log_line": 196,
        "solo_log_label": 208,
        "solo_log_rows": 244,
        "solo_log_step": 32,
        "solo_log_count": 15,
    }

    def __init__(self, controller, on_back: Callable[[], None]) -> None:
        self.ctrl = controller
        self.on_back = on_back
        s = theme.S
        self.w, self.h = theme.window_size(controller.config)
        self.born = motion.now()
        self.kb_index = 0
        self.kb_mode = False
        self._last_progress_draw = 0
        self._last_candidates: list = []
        self._last_move_count = -1
        self._log_y = None            # 走查用：记录棋谱标签 y，验证布局恒定
        self._ai_mode = ai_runner.default_mode()
        self._runner = None           # 全局共享的长驻 AI worker（惰性取用）
        self._ai_submit_at = 0.0     # 当前在途任务的提交时刻（看门狗用）
        self._ai_retry = 0           # 连续超时重试次数，超阈值回退同步
        if self._ai_mode == "async":
            ai_runner.warmup()        # 把 spawn 开销放在场景构造阶段
            self._runner = ai_runner.shared_runner()

        board_rect = (s(36), s(96), s(800), s(690))
        self.board_view = BoardView(board_rect, controller.board,
                                    skins=controller.skins)

        panel_rect = pygame.Rect(s(864), s(96), s(540), s(752))
        self.panel = Panel(panel_rect)

        self.buttons: List[Button] = []
        self._build_buttons(panel_rect)

    # ===================== 控件构建 =====================

    def _build_buttons(self, panel_rect: pygame.Rect) -> None:
        """棋盘下方横排三枚按钮，高 48 逻辑（物理 72px）。"""
        s = theme.S
        self.buttons.clear()
        y, h = s(800), s(48)
        specs = [
            (s(36), s(250), "悔棋", self._undo, False),
            (s(300), s(250), "重新开始", self._restart, False),
            (s(570), s(266), "返回主菜单", self.on_back, True),
        ]
        for i, (x, width, text, callback, accent) in enumerate(specs):
            btn = Button((x, y, width, h), text, on_click=callback,
                         font_size=theme.FONT_BODY, accent=accent)
            btn.reveal_delay = 320 + i * theme.MOTION["stagger"]
            self.buttons.append(btn)

    # ===================== 事件处理 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            self.kb_mode = False
        elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_TAB, pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT,
                pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER):
            self.kb_mode = True
            self.kb_index = keyboard_nav(self.buttons, event, self.kb_index)
            self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))
            return

        for btn in self.buttons:
            if btn.handle_event(event):
                return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            move = self.board_view.pixel_to_cell(event.pos)
            if move is not None:
                self.ctrl.handle_human_move(move)

    def update(self) -> None:
        self.board_view.board = self.ctrl.board
        self.board_view._layout()

        if not self.ctrl.is_over and self.ctrl.current_is_ai:
            self._pump_ai()

        mouse_pos = pygame.mouse.get_pos()
        self.kb_index = min(self.kb_index, max(0, len(self.buttons) - 1))
        for i, btn in enumerate(self.buttons):
            btn.update(mouse_pos)
            btn.focused = self.kb_mode and i == self.kb_index

    # ===================== 多进程 AI 调度 =====================

    def _get_runner(self):
        if self._runner is None:
            self._runner = ai_runner.shared_runner()
        return self._runner

    @staticmethod
    def _apply_snapshot(think, data: dict) -> None:
        """把 worker 回传的 ThinkState 字段写回主进程 AI 实例。"""
        for key, value in data.items():
            setattr(think, key, value)

    def _fallback_sync(self, reason: str) -> None:
        """worker 不可用时退回原来的同步路径，保证对局不中断。"""
        self._ai_mode = "sync"
        self.ctrl.last_event = reason
        self._get_runner().cancel()
        if not self.ctrl.is_over and self.ctrl.current_is_ai:
            self.ctrl.step_ai(on_progress=self._on_ai_progress)

    def _watchdog_timeout(self) -> bool:
        """在途任务超过「最大算法预算 + 6 秒宽限」即判定为卡死。"""
        cfg = self.ctrl.config
        budgets = (cfg.get("mcts_time", 0.0), cfg.get("ab_time", 0.0),
                   cfg.get("evo_time", 0.0))
        limit = max(7.0, max(float(b or 0.0) for b in budgets) + 6.0)
        return (time.monotonic() - self._ai_submit_at) > limit

    def _pump_ai(self) -> None:
        """
        非阻塞地推进一步 AI：提交任务 → 轮询进度 / 结果 → 落子。
        同步模式下保持原有 step_ai(on_progress=...) 语义。
        """
        if self._ai_mode == "sync":
            self.ctrl.step_ai(on_progress=self._on_ai_progress)
            return

        runner = self._get_runner()
        if runner.failed or (runner.busy and not runner.is_alive()):
            self._fallback_sync("AI 进程不可用，已回退同步模式")
            return

        if not runner.busy:
            player = self.ctrl.current_player
            ai = player.ai
            if ai is None:
                return
            ai.think.reset(ai.name, player.player_id)
            self.ctrl.ai_thinking = True
            if not runner.submit(self.ctrl.board.copy(), ai.name,
                                 player.player_id,
                                 self.ctrl.config.to_dict()):
                self._fallback_sync("AI 任务提交失败，已回退同步模式")
                return
            self._ai_submit_at = time.monotonic()
        elif self._ai_submit_at <= 0.0:
            self._ai_submit_at = time.monotonic()
        elif self._watchdog_timeout():
            # worker 卡住但进程仍活着时原有回退条件不成立，必须主动兜底
            self._ai_retry += 1
            runner.cancel()              # 换干净队列，下一帧重新提交
            self.ctrl.ai_thinking = False
            self._ai_submit_at = 0.0
            if self._ai_retry >= 2:
                self._fallback_sync("AI 计算超时，已回退同步模式")
            else:
                self.ctrl.last_event = "AI 响应超时，正在重试"
            return

        msg = runner.poll()
        if msg is None or msg[1] != runner.gen:
            return                      # 无新消息 / 过期世代的结果

        think = None
        if not self.ctrl.is_over and self.ctrl.current_is_ai:
            think = self.ctrl.current_player.ai.think
        kind = msg[0]
        if kind == "progress":
            if think is not None:
                self._apply_snapshot(think, msg[2])
        elif kind == "done":
            self._ai_retry = 0
            if think is not None:
                self._apply_snapshot(think, msg[3])
                think.active = False
            self.ctrl.ai_thinking = False
            self.ctrl.apply_ai_move(msg[2], validate=True)
        else:                            # error
            self._ai_retry = 0
            self.ctrl.ai_thinking = False
            self._fallback_sync("AI 计算失败，已回退同步模式")

    def _cancel_pending(self) -> None:
        """悔棋 / 重开时作废在途任务，避免旧局面的走子落到新棋盘。"""
        if self._ai_mode == "async":
            self._get_runner().cancel()
        self.ctrl.ai_thinking = False
        self._ai_submit_at = 0.0
        self._ai_retry = 0

    def shutdown_ai(self) -> None:
        """切换 / 退出场景时作废在途任务（共享 worker 由 App 统一关闭）。"""
        if self._ai_mode == "async":
            self._get_runner().cancel()

    # ===================== AI 思考可视化回调（契约） =====================

    def _on_ai_progress(self, think) -> None:
        """AI 与界面同线程：主动重绘，按 80ms 限流避免无谓的整屏刷新。"""
        if self.ctrl.is_over:
            return
        now = pygame.time.get_ticks()
        if self._last_progress_draw and \
                now - self._last_progress_draw < theme.THINK_REDRAW_MS:
            return
        self._last_progress_draw = now
        self.draw(self.screen_ref())
        pygame.display.flip()

    def screen_ref(self):
        return pygame.display.get_surface()

    # ===================== 操作回调 =====================

    def _undo(self) -> None:
        self._cancel_pending()
        if self.ctrl.is_over:
            self.ctrl.last_event = "对局已结束，无法悔棋"
            return
        p1_human = self.ctrl.players[BLACK].is_human
        p2_human = self.ctrl.players[WHITE].is_human
        steps = 2 if p1_human != p2_human else 1
        self.ctrl.undo(steps)

    def _restart(self) -> None:
        self._cancel_pending()
        self.ctrl.restart()

    # ===================== 模式与数据源 =====================

    def _ai_sides(self) -> list:
        """本局参与的算法方：[] 人人 / 单元素 人机 / 两元素 算法 PK。"""
        sides = []
        for side in (BLACK, WHITE):
            player = self.ctrl.players.get(side)
            if player is not None and player.ai is not None:
                sides.append(side)
        return sides

    def _think_of(self, side):
        """取某一方 AI 的思考快照；人类方返回 None。"""
        player = self.ctrl.players.get(side)
        ai = getattr(player, "ai", None) if player is not None else None
        return getattr(ai, "think", None) if ai is not None else None

    def _ai_name(self, side) -> str:
        ai = self.ctrl.players[side].ai
        return getattr(ai, "display_name", None) or getattr(ai, "name", "AI")

    def _is_active(self, side) -> bool:
        ai = self._current_thinking_ai()
        player = self.ctrl.players.get(side)
        return (ai is not None and player is not None
                and player.ai is ai and ai.think.active)

    def _sync_candidates(self) -> None:
        """
        候选缓存：只有「落子」才清空旧候选；思考过程中持续更新。
        这样一步结束到下一步开始之间不会瞬间空白，棋盘标记也不闪烁。
        """
        count = len(getattr(self.ctrl, "moves", []) or [])
        if count != self._last_move_count:
            self._last_move_count = count
            self._last_candidates = []
        ai = self._current_thinking_ai()
        if ai is not None and ai.think.top_moves:
            self._last_candidates = list(ai.think.top_moves[:3])

    # ===================== 绘制 =====================

    def _block_label(self, surface, text: str, x: int, y: int) -> None:
        """区块小标：粗体中文 + 左侧朱砂短线。"""
        s = theme.S
        pygame.draw.line(surface, theme.CINNABAR,
                         (x, y + s(4)), (x, y + s(22)), 3)
        label = assets.font("body", s(17), True).render(text, True, theme.INK)
        surface.blit(label, (x + s(14), y))

    def draw(self, surface: pygame.Surface) -> None:
        s = theme.S
        self._sync_candidates()
        surface.blit(atmosphere.paper(self.w, self.h), (0, 0))
        atmosphere.masthead(surface, self.w, "实战对局")

        human_turn = not self.ctrl.is_over and not self.ctrl.current_is_ai
        self.board_view.draw(surface, show_legal_hint=human_turn)
        if self._last_candidates:
            self.board_view.draw_candidate_marks(surface, self._last_candidates)

        self.panel.draw(surface)
        self._draw_status(surface)
        self._draw_think_panel(surface)
        self._draw_move_log(surface)

        for btn in self.buttons:
            btn.reveal = motion.reveal(self.born,
                                       getattr(btn, "reveal_delay", 0),
                                       theme.MOTION["base"])
            btn.draw(surface)

        if self.ctrl.is_over:
            self._draw_result_overlay(surface)

    def _current_thinking_ai(self):
        if self.ctrl.is_over or not self.ctrl.current_is_ai:
            return None
        return self.ctrl.current_player.ai

    def _panel_xy(self):
        p = self.panel.rect
        return p.x + theme.S(24), p.y, p

    def _draw_status(self, surface: pygame.Surface) -> None:
        """右栏顶部：棋种 + 轮到谁（终局显示结果）+ 双方身份 + 一行信息。"""
        s = theme.S
        x, top, panel = self._panel_xy()
        L = self.LAYOUT
        title = GAME_DEFAULTS[self.ctrl.game_kind]["name"]
        head = assets.font("display", s(34)).render(title, True, theme.INK)
        surface.blit(head, (x, top + s(10)))

        state = self.ctrl.result_text() if self.ctrl.is_over \
            else self.ctrl.status_text()
        surface.blit(assets.mixed(s(22), state, theme.CINNABAR),
                     (x, top + s(52)))
        atmosphere.hairline(surface, (x, top + s(L["state_line"])),
                            (panel.right - s(24), top + s(L["state_line"])))

        for i, side in enumerate((BLACK, WHITE)):
            y = top + s(L["identity"][i])
            mark = pygame.Surface((s(12), s(12)), pygame.SRCALPHA)
            mark.fill(theme.BLACK_STONE if i == 0 else theme.WHITE_STONE)
            surface.blit(mark, (x, y + s(4)))
            if i == 1:
                pygame.draw.rect(surface, theme.RULE,
                                 (x, y + s(4), s(12), s(12)), 1)
            surface.blit(assets.mixed(s(18),
                                      self.ctrl.players[side].describe(),
                                      theme.INK),
                         (x + s(24), y))

        atmosphere.hairline(surface, (x, top + s(L["info_line"])),
                            (panel.right - s(24), top + s(L["info_line"])))
        event = self.ctrl.last_event
        info = event or self.ctrl.score_text()
        if info:
            color = theme.CINNABAR if event else theme.INK_SOFT
            surface.blit(assets.mixed(s(17), info, color),
                         (x, top + s(L["info"])))

    # --------------------- 演算区 ---------------------

    @staticmethod
    def _mini_bar(surface, x, y, w, h, ratio, highlight) -> None:
        pygame.draw.rect(surface, theme.RULE_LIGHT, (x, y, w, h),
                         border_radius=theme.RADIUS)
        if ratio > 0:
            color = theme.CINNABAR if highlight else theme.INK_SOFT
            pygame.draw.rect(surface, color,
                             (x, y, max(theme.S(3), int(w * ratio)), h),
                             border_radius=theme.RADIUS)

    @staticmethod
    def _kv_line(surface, x, y, label, value, width, size) -> None:
        s = theme.S
        lab = assets.font("body", s(size)).render(label, True, theme.INK_SOFT)
        val = assets.mixed(s(size), value, theme.INK)
        surface.blit(lab, (x, y))
        surface.blit(val, (x + width - val.get_width(), y))

    @staticmethod
    def _clip(glyph, max_width):
        if glyph.get_width() <= max_width:
            return glyph
        return glyph.subsurface((0, 0, max(1, max_width), glyph.get_height()))

    def _draw_think_card(self, surface, x, y, width, side, active) -> None:
        """单个 AI 的演算卡：单栏与双栏共用，数据不随 active 归零。"""
        s = theme.S
        think = self._think_of(side)
        compact = width < s(400)
        fs = 14 if compact else 17
        side_label = "黑方" if side == BLACK else "白方"

        head = assets.mixed(s(fs), "%s · %s" % (side_label, self._ai_name(side)),
                            theme.CINNABAR if active else theme.INK)
        surface.blit(head, (x, y))
        if active:
            pygame.draw.line(surface, theme.CINNABAR,
                             (x - s(7), y + s(2)),
                             (x - s(7), y + s(20)), 3)

        if think is not None:
            total = think.total or think.max_depth or 1
            ratio = max(0.0, min(1.0, think.done / max(1, total)))
            best = "%s %s" % (self._fmt_move(think.best_move),
                              self._fmt_value(think))
            phase = think.phase or "尚未开始"
            if think.note:
                phase = "%s · %s" % (phase, think.note)
            rows = [("已处理", "%d" % think.done),
                    ("耗时", "%.1f s" % think.elapsed),
                    ("最佳", best)]
        else:
            ratio = 0.0
            phase = "尚未开始"
            rows = [("已处理", "—"), ("耗时", "—"), ("最佳", "—")]

        self._mini_bar(surface, x, y + s(32), width, s(8), ratio, active)
        for i, (label, value) in enumerate(rows):
            self._kv_line(surface, x, y + s(56) + i * s(32),
                          label, value, width, fs)
        glyph = self._clip(assets.mixed(s(13), phase, theme.INK_SOFT), width)
        surface.blit(glyph, (x, y + s(152)))

    def _draw_think_panel(self, surface: pygame.Surface) -> None:
        """按本局 AI 数量分派：无 AI 隐藏、单 AI 单栏、双 AI 双栏对照。"""
        s = theme.S
        x, top, panel = self._panel_xy()
        L = self.LAYOUT
        sides = self._ai_sides()
        if not sides:
            return                     # 人人对战：演算与候选整块不渲染

        atmosphere.hairline(surface, (x, top + s(L["think_line"])),
                            (panel.right - s(24), top + s(L["think_line"])))
        self._block_label(surface, "AI 演算", x, top + s(L["think_label"]))

        body_y = top + s(L["think_body"])
        if len(sides) == 1:
            self._draw_think_card(surface, x, body_y, s(492),
                                  sides[0], self._is_active(sides[0]))
        else:
            # 两列之间的发丝分隔线，让双栏对照一眼可分
            mid = x + s(244)
            pygame.draw.line(surface, theme.RULE_LIGHT,
                             (mid, body_y), (mid, body_y + s(186)))
            for i, side in enumerate((BLACK, WHITE)):
                self._draw_think_card(surface, x + i * s(256), body_y, s(236),
                                      side, self._is_active(side))

        atmosphere.hairline(surface, (x, top + s(L["cand_line"])),
                            (panel.right - s(24), top + s(L["cand_line"])))
        self._block_label(surface, "候选走法", x, top + s(L["cand_label"]))
        self._draw_candidates(surface, x, top + s(L["cand_rows"]),
                              self._last_candidates)

    def _draw_candidates(self, surface, x, y, items) -> None:
        """固定 3 个槽位：无数据时用极淡短横线占位，高度永不变。"""
        s = theme.S
        atmosphere.column_rule(surface, x, y, y + s(102))
        for i in range(3):
            if i < len(items):
                item = items[i]
                mv = self._fmt_coord(item[0])
                value = ("%.1f%%" % (item[2] * 100)) if item[2] else "—"
                line = "%02d   %-5s   %s" % (i + 1, mv, value)
                color = theme.CINNABAR if i == 0 else theme.INK_SOFT
                glyph = assets.mixed(s(17), line, color)
            else:
                glyph = assets.font("mono", s(17)).render(
                    "%02d   —" % (i + 1), True, theme.INK_FAINT)
            surface.blit(glyph, (x + s(14), y + i * s(34)))

    # --------------------- 棋谱区 ---------------------

    def _draw_move_log(self, surface: pygame.Surface) -> None:
        """有 AI 时 4 手、人人对战时 15 手；标签 y 固定（走查可断言）。"""
        s = theme.S
        x, top, panel = self._panel_xy()
        L = self.LAYOUT
        solo = not self._ai_sides()
        prefix = "solo_" if solo else ""
        line_y = L[prefix + "log_line"]
        label_y = L[prefix + "log_label"]
        rows_y = L[prefix + "log_rows"]
        step = L[prefix + "log_step"]
        count = L[prefix + "log_count"]
        self._log_y = top + s(label_y)

        atmosphere.hairline(surface, (x, top + s(line_y)),
                            (panel.right - s(24), top + s(line_y)))
        self._block_label(surface, "棋谱", x, top + s(label_y))
        column_y = top + s(rows_y)
        atmosphere.column_rule(surface, x, column_y,
                               column_y + s(step * count))

        moves = list(getattr(self.ctrl, "moves", []) or [])
        recent = moves[-count:]
        base = len(moves) - len(recent)
        for i, mv in enumerate(recent):
            who = "黑" if mv.get("player") == BLACK else "白"
            line = "%03d   %s   %s" % (base + i + 1, who,
                                       self._fmt_coord(mv.get("move")))
            color = theme.CINNABAR if i == len(recent) - 1 else theme.INK_SOFT
            surface.blit(assets.mixed(s(17), line, color),
                         (x + s(14), column_y + i * s(step)))
        if not recent:
            surface.blit(assets.mixed(s(17), "尚无落子 · 落子后在此逐手记录",
                                      theme.INK_SOFT),
                         (x + s(14), column_y))

    # --------------------- 格式化与终局 ---------------------

    @staticmethod
    def _fmt_move(move) -> str:
        if move is None:
            return "—"
        return "(%d,%d)" % (move[0], move[1])

    def _fmt_coord(self, move) -> str:
        if not move:
            return "—"
        n = self.ctrl.board.size
        col = chr(65 + move[1]) if move[1] < 26 else str(move[1])
        return "%s%d" % (col, n - move[0])

    @staticmethod
    def _fmt_value(think) -> str:
        if think.algo == "mcts":
            return "%.1f%%" % (think.best_value * 100)
        return "%.0f 分" % think.best_value

    def _draw_result_overlay(self, surface: pygame.Surface) -> None:
        s = theme.S
        rect = self.board_view.rect
        overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        overlay.fill((*theme.PAPER, 214))
        surface.blit(overlay, rect.topleft)
        pygame.draw.line(surface, theme.CINNABAR,
                         (rect.x + s(56), rect.centery - s(72)),
                         (rect.x + s(160), rect.centery - s(72)), 4)
        result = assets.font("display", s(44)).render(
            self.ctrl.result_text(), True, theme.INK)
        surface.blit(result, result.get_rect(center=(rect.centerx,
                                                     rect.centery)))
