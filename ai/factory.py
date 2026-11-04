# -*- coding: utf-8 -*-
"""
AI 工厂：根据算法名称字符串实例化对应算法对象。

对局层只需传入 'mcts' / 'alphabeta' / 'random'，无需关心具体类构造细节；
后续新增算法时，在注册表 _REGISTRY 中登记即可被主程序识别。
"""

from typing import Optional

from .base_ai import BaseAI
from .mcts import MCTSAI
from .alpha_beta import AlphaBetaAI
from .random_ai import RandomAI
from .llm_ai import LlmAI
from .llm_assisted import LlmAssistedAI
from utils.logger import log_warn

# 算法标识 → 算法类 的注册表
_REGISTRY = {
    "mcts": MCTSAI,
    "alphabeta": AlphaBetaAI,
    "random": RandomAI,
    "llm": LlmAI,
    "llm_mcts": LlmAssistedAI,
}


def create_ai(algo_name: Optional[str], player: int, config) -> Optional[BaseAI]:
    """
    工厂方法：创建 AI 实例。

    参数：
        algo_name: 算法标识；None 表示该方为人类玩家，返回 None；
        player:    AI 代表的玩家编号（BLACK / WHITE）；
        config:    全局运行配置。
    返回：
        对应 AI 实例；algo_name 为 None 时返回 None。
    """
    if algo_name is None:
        return None

    if algo_name not in _REGISTRY:
        log_warn(f"未知 AI 算法 {algo_name}，已退回随机策略")
        algo_name = "random"

    return _REGISTRY[algo_name](player, config)
