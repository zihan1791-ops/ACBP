# -*- coding: utf-8 -*-
"""
AI 抽象基类：定义所有算法对外统一的选择走子接口与思考可视化接口。

对局控制器（game.controller）只依赖本基类，不关心具体算法是 MCTS、
Alpha-Beta 还是随机策略；新增算法时只需继承本类并实现 select_move()。

每个 AI 实例持有一个 ThinkState，select_move() 计算过程中持续更新它，
并通过 on_progress 回调通知界面实时重绘「AI 思考过程」。
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from .think_state import ThinkState


class BaseAI(ABC):
    """AI 算法抽象父类。"""

    # 算法标识名称（用于界面显示与日志）
    name = "base"

    def __init__(self, player: int, config) -> None:
        """
        参数：
            player: 该 AI 代表的玩家编号（BLACK / WHITE）；
            config: 全局运行配置对象（Config），提供搜索预算参数。
        """
        self.player = player
        self.config = config
        # 思考过程状态：界面实时读取并可视化
        self.think = ThinkState()

    @abstractmethod
    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        """
        在给定棋盘局面上选择一步合法走子。

        参数：
            board:       棋盘状态；
            on_progress: 可选回调，思考过程中定期调用，参数为当前 ThinkState，
                         界面借此实现实时可视化。
        返回：
            (row, col) 选中的合法走子；
            None 表示当前局面无可走步（例如被迫停一手）。
        """

    # -------------------- 思考可视化工具 --------------------

    def _begin_think(self) -> None:
        """开启新一步思考：重置思考状态。"""
        self.think.reset(self.name, self.player)

    def _emit(self, on_progress) -> None:
        """向界面推送一次思考进度（若提供了回调）。"""
        if on_progress is not None:
            on_progress(self.think)

    @property
    def label(self) -> str:
        """返回「黑方 MCTS」形式的显示标签。"""
        from core.base_board import BLACK
        side = "黑方" if self.player == BLACK else "白方"
        return f"{side} {self.name}"
