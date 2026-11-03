# -*- coding: utf-8 -*-
"""
大模型设置场景（LlmSettingsScene）。

功能：
1. 在主菜单点击「大模型设置」进入；
2. 输入 / 修改 API Key，保存到本机 config/llm_keys.json（明文），
   下次对局自动读取，免重复输入；
3. 可一键清除已保存的 Key，返回主菜单继续配局。

展示当前接入的模型名（默认 deepseek-flash）与是否已配置状态。
"""

import pygame
from typing import Callable

from . import theme
from .widgets import Button, draw_text
from .input_box import InputBox
from config.llm_keys import load_api_key, save_api_key, clear_api_key


class LlmSettingsScene:
    """大模型 API Key 配置界面。"""

    def __init__(self, cfg, on_back: Callable[[], None]) -> None:
        self.cfg = cfg
        self.on_back = on_back
        w = theme.S(cfg.window_width)
        self.w = w
        cx = w // 2

        # 已保存的 Key（用于状态展示），输入框留空表示保留原值
        self.saved_key = load_api_key(cfg.llm_model)
        self.msg = ""
        self.msg_color = theme.TEXT

        # 输入框（掩码显示）
        self.input_box = InputBox(
            pygame.Rect(cx - theme.S(240), theme.S(220),
                        theme.S(480), theme.S(48)),
            placeholder="粘贴 API Key（sk-…）", secret=True,
        )

        self.buttons: list = []
        # 保存
        self.buttons.append(Button(
            pygame.Rect(cx - theme.S(90), theme.S(300),
                        theme.S(180), theme.S(44)),
            "保存", on_click=self._save, accent=True,
            font_size=theme.FONT_BODY))
        # 清除
        self.buttons.append(Button(
            pygame.Rect(cx - theme.S(90), theme.S(360),
                        theme.S(180), theme.S(40)),
            "清除 Key", on_click=self._clear,
            font_size=theme.FONT_BODY))
        # 返回主菜单
        self.buttons.append(Button(
            pygame.Rect(cx - theme.S(100), theme.S(470),
                        theme.S(200), theme.S(40)),
            "返回主菜单", on_click=self.on_back, accent=True,
            font_size=theme.FONT_BODY))

    # ===================== 操作回调 =====================

    def _save(self) -> None:
        """保存输入框中的 Key；空输入时提示。"""
        key = self.input_box.text.strip()
        if not key:
            self.msg = "请输入 API Key 后再保存"
            self.msg_color = theme.WARN
            return
        save_api_key(key, self.cfg.llm_model)
        self.saved_key = key
        self.input_box.text = ""
        self.msg = "已保存，对局时将自动读取（可在本页随时修改）"
        self.msg_color = theme.ACCENT_DARK

    def _clear(self) -> None:
        """清除已保存的 Key。"""
        if clear_api_key(self.cfg.llm_model):
            self.saved_key = ""
            self.msg = "已清除 API Key"
            self.msg_color = theme.ACCENT_DARK
        else:
            self.msg = "当前未配置 API Key，无需清除"
            self.msg_color = theme.WARN

    # ===================== 事件 / 更新 / 绘制 =====================

    def handle_event(self, event: pygame.event.Event) -> None:
        """分发按钮点击与输入框键盘事件。"""
        for btn in self.buttons:
            if btn.handle_event(event):
                return
        self.input_box.handle_event(event)

    def update(self) -> None:
        """刷新按钮悬停态与输入框光标。"""
        mouse_pos = pygame.mouse.get_pos()
        for btn in self.buttons:
            btn.update(mouse_pos)
        self.input_box.update(16)

    def draw(self, surface: pygame.Surface) -> None:
        """绘制标题、说明、状态、输入框与按钮。"""
        surface.fill(theme.BG)
        cx = self.w // 2

        draw_text(surface, "大模型设置", cx, theme.S(56),
                  size=theme.FONT_TITLE, color=theme.TEXT, align="center")
        draw_text(surface,
                  f"接入 DeepSeek 官方 API（模型 {self.cfg.llm_model}），"
                  "输入 Key 保存后对局自动调用",
                  cx, theme.S(104), size=theme.FONT_SMALL,
                  color=theme.TEXT_LIGHT, align="center")

        # 当前状态行
        if self.saved_key:
            tail = self.saved_key[-4:]
            state = f"当前状态：已保存（…{tail}）"
        else:
            state = "当前状态：未配置 API Key"
        draw_text(surface, state, cx, theme.S(170),
                  size=theme.FONT_SMALL,
                  color=theme.ACCENT_DARK if self.saved_key else theme.WARN,
                  align="center")

        self.input_box.draw(surface)

        # 操作结果提示
        if self.msg:
            draw_text(surface, self.msg, cx, theme.S(432),
                      size=theme.FONT_SMALL, color=self.msg_color,
                      align="center")

        draw_text(surface,
                  "Key 仅明文保存在本机 config/llm_keys.json，"
                  "不会上传到本游戏以外的任何地方",
                  cx, theme.S(540), size=theme.FONT_SMALL,
                  color=theme.TEXT_LIGHT, align="center")

        for btn in self.buttons:
            btn.draw(surface)
