# -*- coding: utf-8 -*-
"""规则核心包：与界面、AI 解耦，仅维护棋盘状态与合法规则。"""
from .base_board import BaseBoard, EMPTY, BLACK, WHITE, DRAW
from .gomoku.board import GomokuBoard
from .othello.board import OthelloBoard
from .go.board import GoBoard

# 棋种标识 → 棋盘类 的工厂映射，供 game 层与 UI 层统一创建
BOARD_CLASSES = {
    "gomoku": GomokuBoard,
    "othello": OthelloBoard,
    "go": GoBoard,
}

__all__ = [
    "BaseBoard", "EMPTY", "BLACK", "WHITE", "DRAW",
    "GomokuBoard", "OthelloBoard", "GoBoard", "BOARD_CLASSES",
]
