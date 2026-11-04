# -*- coding: utf-8 -*-
"""
对局场景（GameScene）。

职责：
1. 左侧绘制棋盘并响应人类鼠标落子；
2. 右侧信息面板显示双方身份、当前回合、子力 / 提子、提示消息；
3. 提供悔棋、重开、返回菜单等操作按钮；
4. 在 AI 回合自动推进一步，并通过 on_progress 回调实现「AI 思考过程
   可视化」：AI 计算期间实时重绘画面，展示搜索进度条、当前阶段、耗时、
   迭代数 / 节点数、最佳走法与棋盘上的 Top 候选高亮。

本场景只通过 GameController 操作棋局，不直接修改规则棋盘。
"""

import pygame
from typing import Callable, List

from . import theme
from .board_view import BoardView
from .widgets import Button, Panel, ProgressBar, draw_text
from core.base_board import BLACK, WHITE
from config import GAME_DEFAULTS


class GameScene:
    """单局对局的交互与渲染场景。"""

    def __init__(self, controller, on_back: Callable[[], None]) -> None:
        self.ctrl = controller
        self.on_back = on_back

        cfg = controller.config
        w, h = theme.S(cfg.window_width), theme.S(cfg.window_height)

        # 左侧棋盘视图区域
        board_rect = (theme.PAD, theme.PAD, int(w * 0.66), h - theme.PAD * 2)
        self.board_view = BoardView(board_rect, controller.board)

        # 右侧信息面板区域
        panel_x = int(w * 0.66) + theme.PAD * 2
        panel_rect = pygame.Rect(panel_x, theme.PAD,
                                 w - panel_x - theme.PAD, h - theme.PAD * 2)
        self.panel = Panel(panel_rect)

        self.buttons: List[Button] = []
        self._build_buttons(panel_rect)

        # AI 思考进度条（面板内固定区域，构造后常驻）
        self.think_bar = ProgressBar(
            pygame.Rect(panel_rect.x + theme.S(18), panel_rect.y + theme.S(318),
                        panel_rect.width - theme.S(36), theme.S(18)),
            max_value=0.0, label="AI 思考中…")

    # ===================== 控件构建 =====================

    def _build_buttons(self, panel_rect: pygame.Rect) -> None:
        """在右侧面板底部垂直排列操作按钮（围棋已停用，正常 3 个按钮）。"""
        x = panel_rect.x + theme.S(16)
        btn_w = panel_rect.width - theme.S(32)
        btn_h = theme.S(42)
        gap = theme.S(12)
        # 固定起始纵坐标，依次向下排列，保证不溢出面板
        y = panel_rect.y + theme.S(430)

        # 悔棋
        self.buttons.append(Button(pygame.Rect(x, y, btn_w, btn_h),
                                    "悔棋", on_click=self._undo))
        y += btn_h + gap
        # 重开
        self.buttons.append(Button(pygame.Rect(x, y, btn_w, btn_h),
                                    "重新开始", on_click=self._restart))
        y += btn_h + gap
        # 返回主菜单
        self.buttons.append(Button(pygame.Rect(x, y, btn_w, btn_h),
                                    "返回主菜单", on_click=self.on_back, accent=True))

    # ===================== 事件处理 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        """先处理按钮点击；未命中按钮时再把点击换算为棋盘落子。"""
        for btn in self.buttons:
            if btn.handle_event(event):
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            move = self.board_view.pixel_to_cell(event.pos)
            if move is not None:
                self.ctrl.handle_human_move(move)

    def update(self) -> None:
        """同步棋盘引用；轮到 AI 时自动落子一步；刷新按钮悬停态。"""
        # 悔棋 / 重开会替换棋盘对象，这里保持视图引用同步并重新计算布局
        self.board_view.board = self.ctrl.board
        self.board_view._layout()

        if not self.ctrl.is_over and self.ctrl.current_is_ai:
            # 传入思考进度回调：AI 计算过程中会反复调用，实时重绘画面
            self.ctrl.step_ai(on_progress=self._on_ai_progress)

        mouse_pos = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.update(mouse_pos)

    # ===================== AI 思考可视化回调 =====================

    def _on_ai_progress(self, think) -> None:
        """
        AI 思考过程回调：每推送一次进度就重绘当前画面并刷新屏幕。

        由于 AI 与界面同线程，计算期间主循环被阻塞，必须由本回调主动
        重绘 + flip，才能让玩家实时看到搜索进度与候选高亮。
        """
        if self.ctrl.is_over:
            return
        self.draw(self.screen_ref())
        pygame.display.flip()

    def screen_ref(self):
        """返回当前绘制目标（由 update 所在循环持有）。"""
        # 简化：直接使用 pygame.display 的当前表面
        return pygame.display.get_surface()

    # ===================== 操作回调 =====================

    def _undo(self) -> None:
        """悔棋：人机大战回退两步（人一步 + AI 一步），其它模式回退一步。"""
        if self.ctrl.is_over:
            self.ctrl.last_event = "对局已结束，无法悔棋"
            return
        p1_human = self.ctrl.players[BLACK].is_human
        p2_human = self.ctrl.players[WHITE].is_human
        steps = 2 if p1_human != p2_human else 1
        self.ctrl.undo(steps)

    def _restart(self) -> None:
        """复原到开局局面。"""
        self.ctrl.restart()

    # ===================== 绘制 =====================

    def draw(self, surface: pygame.Surface) -> None:
        """绘制背景、棋盘、右侧信息面板、AI 思考区、操作按钮与终局遮罩。"""
        surface.fill(theme.BG)

        # 当前是否人类回合（用于绘制合法步提示点）
        human_turn = not self.ctrl.is_over and not self.ctrl.current_is_ai
        self.board_view.draw(surface, show_legal_hint=human_turn)

        # AI 思考候选高亮（思考激活时在棋盘上标记 Top 候选）
        thinking_ai = self._current_thinking_ai()
        if thinking_ai is not None and thinking_ai.think.active:
            self.board_view.draw_candidate_marks(surface, thinking_ai.think.top_moves)

        self.panel.draw(surface)
        self._draw_panel(surface)
        self._draw_think_panel(surface)

        for btn in self.buttons:
            btn.draw(surface)

        if self.ctrl.is_over:
            self._draw_result_overlay(surface)

    def _current_thinking_ai(self):
        """返回当前正在思考的 AI（未轮到 AI 时返回 None）。"""
        if self.ctrl.is_over or not self.ctrl.current_is_ai:
            return None
        return self.ctrl.current_player.ai

    def _draw_panel(self, surface: pygame.Surface) -> None:
        """绘制右侧面板内的身份、状态、得分与提示信息。"""
        panel = self.panel.rect
        title = GAME_DEFAULTS[self.ctrl.game_kind]["name"]
        draw_text(surface, title, panel.x + theme.S(18), panel.y + theme.S(18),
                  size=theme.FONT_HEAD, color=theme.TEXT)

        # 双方身份描述
        black = self.ctrl.players[BLACK]
        white = self.ctrl.players[WHITE]
        draw_text(surface, black.describe(), panel.x + theme.S(18), panel.y + theme.S(78),
                  size=theme.FONT_BODY, color=theme.TEXT)
        draw_text(surface, white.describe(), panel.x + theme.S(18), panel.y + theme.S(114),
                  size=theme.FONT_BODY, color=theme.TEXT)

        # 分隔线
        pygame.draw.line(surface, theme.PANEL_BORDER,
                         (panel.x + theme.S(18), panel.y + theme.S(158)),
                         (panel.right - theme.S(18), panel.y + theme.S(158)), 1)

        # 当前回合状态
        draw_text(surface, self.ctrl.status_text(), panel.x + theme.S(18), panel.y + theme.S(186),
                  size=theme.FONT_BODY, color=theme.ACCENT_DARK)

        # 子力 / 提子信息
        score = self.ctrl.score_text()
        if score:
            draw_text(surface, score, panel.x + theme.S(18), panel.y + theme.S(230),
                      size=theme.FONT_SMALL, color=theme.TEXT_LIGHT)

        # 最近提示消息（如非法落子、悔棋结果）
        if self.ctrl.last_event:
            draw_text(surface, self.ctrl.last_event, panel.x + theme.S(18), panel.y + theme.S(262),
                      size=theme.FONT_SMALL, color=theme.WARN)

    def _draw_think_panel(self, surface: pygame.Surface) -> None:
        """绘制「AI 思考中」信息区：进度条、阶段、深度、耗时、最佳步与 Top 候选。"""
        thinking_ai = self._current_thinking_ai()
        if thinking_ai is None:
            return

        think = thinking_ai.think
        panel = self.panel.rect

        if not think.active:
            # 思考结束：显示最终结论一行即可
            move_text = self._fmt_move(think.best_move)
            draw_text(surface, f"AI 思考完成，选择 {move_text}",
                      panel.x + theme.S(18), panel.y + theme.S(296),
                      size=theme.FONT_SMALL, color=theme.ACCENT_DARK)
            return

        # 进度条（MCTS / 大模型+MCTS 按迭代总量、Alpha-Beta 按深度总量）
        if think.algo in ("mcts", "llm_mcts"):
            self.think_bar.max_value = think.total or 1
            self.think_bar.label = f"AI 思考中 · {think.phase}"
        else:
            self.think_bar.max_value = think.max_depth or 1
            self.think_bar.label = f"AI 思考中 · {think.phase}"
        self.think_bar.draw(surface, think.done)

        # 统计行：深度 / 节点数、耗时
        depth_text = (f"深度 {think.depth}/{think.max_depth}"
                      if think.algo not in ("mcts", "llm_mcts") else "")
        info = f"{depth_text} 已处理 {think.done}  耗时 {think.elapsed:.1f}s"
        draw_text(surface, info, panel.x + theme.S(18), panel.y + theme.S(352),
                  size=theme.FONT_SMALL, color=theme.TEXT_LIGHT)

        # 当前最佳走法
        move_text = self._fmt_move(think.best_move)
        value_text = self._fmt_value(think)
        draw_text(surface, f"当前最佳：{move_text}（{value_text}）",
                  panel.x + theme.S(18), panel.y + theme.S(374),
                  size=theme.FONT_SMALL, color=theme.TEXT)

        # Top 候选列表（MCTS 提供访问数与胜率；Alpha-Beta 提供评估序）
        if think.top_moves:
            parts = []
            for idx, item in enumerate(think.top_moves[:3], start=1):
                mv = self._fmt_move(item[0])
                if item[2]:
                    parts.append(f"{idx} {mv} {item[2]:.0%}")
                else:
                    parts.append(f"{idx} {mv}")
            draw_text(surface, "Top 候选： " + "  ".join(parts),
                      panel.x + theme.S(18), panel.y + theme.S(396),
                      size=theme.FONT_SMALL, color=theme.BLUE)

        # 附加说明（如「强制防守」）
        if think.note:
            draw_text(surface, f"提示：{think.note}",
                      panel.x + theme.S(18), panel.y + theme.S(416),
                      size=theme.FONT_SMALL, color=theme.WARN)

    @staticmethod
    def _fmt_move(move) -> str:
        """把 (row, col) 格式化为 (行,列) 文本；None 显示「—」。"""
        if move is None:
            return "—"
        return f"({move[0]},{move[1]})"

    @staticmethod
    def _fmt_value(think) -> str:
        """格式化当前最佳步的价值：MCTS / 混合棋手显示胜率，Alpha-Beta 显示评分。"""
        if think.algo in ("mcts", "llm_mcts"):
            return f"{think.best_value:.1%}"
        return f"{think.best_value:.0f} 分"

    def _draw_result_overlay(self, surface: pygame.Surface) -> None:
        """对局结束时在棋盘区叠加半透明遮罩与最终结果文字。"""
        rect = self.board_view.rect
        overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        overlay.fill((245, 241, 232, 180))
        surface.blit(overlay, rect.topleft)

        draw_text(surface, self.ctrl.result_text(),
                  rect.centerx, rect.centery - theme.S(20),
                  size=theme.FONT_TITLE, color=theme.TEXT, align="center")
        draw_text(surface, "可点击「重新开始」再来一局，或「返回主菜单」切换棋种",
                  rect.centerx, rect.centery + theme.S(28),
                  size=theme.FONT_SMALL, color=theme.TEXT_LIGHT, align="center")
