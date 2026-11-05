# -*- coding: utf-8 -*-
"""AI 算法包：统一接口 + 搜索算法 + 群体优化选步算法。"""
from .base_ai import BaseAI
from .mcts import MCTSAI
from .alpha_beta import AlphaBetaAI
from .random_ai import RandomAI
from .evolution import (ImprovedGeneticAI, DifferentialEvolutionAI,
                        ParticleSwarmAI, ArtificialBeeColonyAI)
from .factory import create_ai

__all__ = ["BaseAI", "MCTSAI", "AlphaBetaAI", "RandomAI",
           "ImprovedGeneticAI", "DifferentialEvolutionAI",
           "ParticleSwarmAI", "ArtificialBeeColonyAI", "create_ai"]
