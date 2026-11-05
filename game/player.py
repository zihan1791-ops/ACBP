# -*- coding: utf-8 -*-
"""
玩家封装：把「人类玩家」与「AI 玩家」包装成统一对象。

对局控制器只面向 Player 编程：通过 is_human 判断当前回合该等待鼠标输入，
还是调用 AI 的 select_move()，从而无需在控制器中区分玩家类型。
"""

from typing import Optional

from core.base_board import BLACK
from ai.base_ai import BaseAI
from config.skins import normalize


class Player:
    """对局玩家（人类或 AI）。"""

    def __init__(self, player_id: int, name: str, ai: Optional[BaseAI] = None,
                 skin: Optional[str] = None) -> None:
        """
        参数：
            player_id: 玩家编号（BLACK=1 黑方 / WHITE=2 白方）；
            name:      界面显示名称；
            ai:        AI 实例；None 表示人类玩家；
            skin:      棋子外观标识；None 或非法值按玩家编号取默认外观。
        """
        self.player_id = player_id
        self.name = name
        self.ai = ai
        self.skin = normalize(skin, player_id)

    @property
    def is_human(self) -> bool:
        """是否为人类玩家。"""
        return self.ai is None

    @property
    def side_label(self) -> str:
        """返回「黑方 / 白方」中文标签。"""
        return "黑方" if self.player_id == BLACK else "白方"

    def describe(self) -> str:
        """返回完整身份描述，用于侧栏信息展示。"""
        if self.is_human:
            return f"{self.side_label}（人类）"
        # 优先使用 AI 的中文显示名，无则退回算法标识
        display = getattr(self.ai, "display_name", self.ai.name)
        return f"{self.side_label}（{display}）"
