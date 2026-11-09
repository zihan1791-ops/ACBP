# -*- coding: utf-8 -*-
"""OBF（Othello Board Format）局面序列化与 Edax 代数坐标换算。"""

import re

from core.base_board import BLACK, WHITE

# Edax 输出的主变例首着形如 d3 / F5；A~H 为列、1~8 为行
MOVE_RE = re.compile(r"\b([A-Ha-h])([1-8])\b")


def board_to_obf(board) -> str:
    """项目二维棋盘 → 64 字符行优先 + 轮次标记（X 黑 / O 白 / - 空）。"""
    cells = []
    for row in board.board:
        for value in row:
            if value == BLACK:
                cells.append("X")
            elif value == WHITE:
                cells.append("O")
            else:
                cells.append("-")
    turn = "X" if board.current_player == BLACK else "O"
    return "".join(cells) + " " + turn + ";"


def notation_to_rc(text):
    """把 D3 / f5 之类的记法换成项目 (row, col)，行从 0 开始。"""
    m = MOVE_RE.search(text)
    if m is None:
        return None
    return int(m.group(2)) - 1, ord(m.group(1).upper()) - ord("A")
