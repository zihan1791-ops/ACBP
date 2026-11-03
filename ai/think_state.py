# -*- coding: utf-8 -*-
"""
AI 思考过程状态（ThinkState）。

用途：让界面可以实时读取 AI 正在进行的计算过程——当前阶段、已迭代 / 已评估
节点数、搜索深度、耗时、当前最佳走法与 Top 候选列表，从而把「AI 怎么想」
可视化出来（进度条 + 棋盘候选高亮 + 胜率 / 分值列表）。

每个 AI 实例持有一个 ThinkState；select_move() 在计算过程中持续更新它，
并通过 on_progress 回调通知界面重绘。
"""

from typing import List, Optional, Tuple


class ThinkState:
    """一份可被界面实时读取的 AI 思考过程快照。"""

    def __init__(self) -> None:
        self.reset(algo="", player=0)

    def reset(self, algo: str, player: int) -> None:
        """开始新一步思考：清空全部统计字段并置为激活状态。"""
        self.active: bool = True        # 是否正在思考
        self.algo: str = algo           # 算法名称（mcts / alphabeta / random）
        self.player: int = player       # 思考方玩家编号
        self.phase: str = ""            # 当前阶段描述，如「迭代加深 · 第 3 层」
        self.done: int = 0              # 已完成工作量（MCTS 迭代数 / αβ 已评估节点数）
        self.total: int = 0             # 工作总量预算（0 表示无总量概念）
        self.depth: int = 0             # 当前搜索深度
        self.max_depth: int = 0         # 搜索深度上限
        self.elapsed: float = 0.0       # 已耗时（秒）
        self.best_move: Optional[Tuple[int, int]] = None   # 当前最佳走法
        self.best_value: float = 0.0    # 当前最佳走法的胜率 / 评估分
        self.top_moves: List[Tuple[Tuple[int, int], int, float]] = []
        # top_moves 元素为 (坐标, 访问次数或评估序, 胜率或分值)，供界面高亮 Top 候选
        self.note: str = ""             # 附加说明，如「检测到冲四，强制防守」

    def finish(self) -> None:
        """思考结束：置为非激活状态。"""
        self.active = False
