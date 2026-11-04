# -*- coding: utf-8 -*-
"""
局面评估函数库。

作用：为 Alpha-Beta 剪枝搜索在叶子节点提供「局面优劣」量化分值；
分值以评估方 player 视角给出：正数表示 player 占优，负数表示对手占优。
不同棋种使用各自适配的评估策略，通过棋盘类名自动分发。

注意：终局胜负由棋盘规则层判定并给出极大 / 极小奖励（在 alpha_beta 中
实现），本模块只负责中盘局面的启发式打分。
"""

from typing import List, Tuple

from core.base_board import EMPTY, BLACK


# -------------------- 黑白棋位置权重表（8×8） --------------------
# 设计思路：角落价值最高且无法被翻转；紧邻角落的位置最容易让对方抢角，
# 价值很低；边中段与中心位置价值居中。该权重表是黑白棋经典位置启发式。
_OTHELLO_WEIGHTS: List[List[int]] = [
    [120, -20,  20,   5,   5,  20, -20, 120],
    [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
    [ 20,  -5,  15,   3,   3,  15,  -5,  20],
    [  5,  -5,   3,   3,   3,   3,  -5,   5],
    [  5,  -5,   3,   3,   3,   3,  -5,   5],
    [ 20,  -5,  15,   3,   3,  15,  -5,  20],
    [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
    [120, -20,  20,   5,   5,  20, -20, 120],
]


def evaluate(board, player: int) -> float:
    """根据棋盘类型自动选择评估器，返回 player 视角的局面分值。"""
    class_name = type(board).__name__
    if class_name == "GomokuBoard":
        return _gomoku_score(board, player)
    if class_name == "OthelloBoard":
        return _othello_score(board, player)
    if class_name == "GoBoard":
        return _go_score(board, player)
    return 0.0


# ===================== 五子棋评估 =====================

# 五子棋四方向
_GOMOKU_DIRS: List[Tuple[int, int]] = [
    (0, 1), (1, 0), (1, 1), (1, -1),
]


def _pattern_score(count: int, open_ends: int) -> int:
    """
    根据连续棋子数与开放端数量给出棋型分值。

    参数：
        count:     连续同色棋子数量；
        open_ends: 连段两端的空位数量（0=两端被堵，1=一端开放，2=两端开放）。

    关键修正：双端被堵的连段（open_ends==0）是死型——永远不会再延伸成五，
    即使四连也不具威胁，分值必须接近 0；真正的价值集中在至少一端开放
    （活三 / 活四 / 冲四）的棋型上。此修正让「堵住对手活三 / 活四」的
    防守价值能在局面评估中如实体现。
    """
    if count >= 5:
        # 五连（理论上终局已提前判定，这里作为兜底高分）
        return 100000
    if count == 4:
        if open_ends == 2:
            return 12000   # 活四：双端可成五，必胜威胁
        if open_ends == 1:
            return 1500    # 冲四：单端可成五，必须立即防守
        return 5           # 双端封死的四连：死型，无威胁
    if count == 3:
        if open_ends == 2:
            return 1200    # 活三：下一步活四
        if open_ends == 1:
            return 120     # 眠三 / 冲三：有限威胁
        return 10          # 双端封死的三连：死型
    if count == 2:
        if open_ends == 2:
            return 120
        if open_ends == 1:
            return 12
        return 2
    if count == 1:
        return 8 if open_ends == 2 else (2 if open_ends == 1 else 1)
    return 0


def _gomoku_line_score(board, r: int, c: int, dr: int, dc: int, player: int) -> int:
    """
    统计 (r, c) 处沿 (dr, dc) 方向属于 player 的连段分值。
    仅在连段起点（前一格不是己方棋子）统计一次，避免同一棋型重复计分。
    """
    # 前一格不是己方棋子，说明当前点是该连段在本方向上的起点
    pr, pc = r - dr, c - dc
    if board.in_bounds(pr, pc) and board.board[pr][pc] == player:
        return 0

    # 向后统计连续己方棋子长度
    count = 0
    rr, cc = r, c
    while board.in_bounds(rr, cc) and board.board[rr][cc] == player:
        count += 1
        rr += dr
        cc += dc

    # 统计两端是否为空位（开放端数量）
    open_ends = 0
    # 棋盘外没有可落子点，视为封闭端而不是开放端。
    if board.in_bounds(pr, pc) and board.board[pr][pc] == EMPTY:
        open_ends += 1
    if board.in_bounds(rr, cc) and board.board[rr][cc] == EMPTY:
        open_ends += 1

    return _pattern_score(count, open_ends)


def _gomoku_score(board, player: int) -> float:
    """五子棋局面评估：己方全部棋型得分之和减去对手棋型得分之和。"""
    opponent = board.opponent(player)
    player_score = 0
    opponent_score = 0

    for r in range(board.size):
        for c in range(board.size):
            piece = board.board[r][c]
            if piece == EMPTY:
                continue
            for dr, dc in _GOMOKU_DIRS:
                if piece == player:
                    player_score += _gomoku_line_score(board, r, c, dr, dc, player)
                else:
                    opponent_score += _gomoku_line_score(board, r, c, dr, dc, opponent)

    # 同时关注「威胁反制」：对手高分棋型要更重地扣分
    return player_score - opponent_score * 1.1


# ===================== 黑白棋评估 =====================

def _othello_score(board, player: int) -> float:
    """
    黑白棋评估（三要素加权）：
    1. 位置权重差：角 > 边 > 中心，是最重要的长期价值；
    2. 机动性差：合法步数多的一方更主动，是黑白棋经典中期指标；
    3. 子力差的方向随阶段切换：中盘鼓励「少子灵活」（避免贪翻子被反杀），
       残局鼓励「多子取胜」（终局以子数定胜负）。
    """
    opponent = board.opponent(player)
    player_weight = opponent_weight = 0
    player_count = opponent_count = 0

    for r in range(board.size):
        for c in range(board.size):
            cell = board.board[r][c]
            weight = _OTHELLO_WEIGHTS[r][c]
            if cell == player:
                player_weight += weight
                player_count += 1
            elif cell == opponent:
                opponent_weight += weight
                opponent_count += 1

    # 机动性：分别统计双方合法步数（临时切换 current_player，结束后恢复）
    saved = board.current_player
    board.current_player = player
    player_mobility = len(board.get_legal_moves())
    board.current_player = opponent
    opponent_mobility = len(board.get_legal_moves())
    board.current_player = saved

    total = player_count + opponent_count
    midgame = total < 44  # 8×8 共 64 格：44 子以前视为中盘
    piece_diff = player_count - opponent_count
    if midgame:
        piece_term = -piece_diff * 1.0     # 中盘：子少反而加分（保持灵活）
    else:
        piece_term = piece_diff * 3.0      # 残局：子多获胜

    return ((player_weight - opponent_weight) * 10.0
            + (player_mobility - opponent_mobility) * 5.0
            + piece_term)


# ===================== 围棋简化评估 =====================

def _go_liberties(board, player: int) -> int:
    """粗略统计 player 全部棋子的气数（相邻空位计数，不做连通块去重）。"""
    liberties = 0
    for r in range(board.size):
        for c in range(board.size):
            if board.board[r][c] != player:
                continue
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if board.in_bounds(nr, nc) and board.board[nr][nc] == EMPTY:
                    liberties += 1
    return liberties


def _go_score(board, player: int) -> float:
    """
    围棋中盘简化评估：棋子数差 + 气数差 + 提子差。
    专业布局 / 厚薄判断不在课程版本评估范围内。
    """
    opponent = board.opponent(player)
    p_stones, o_stones = board.count_pieces()

    # 提子差按归属方换算
    if player == BLACK:
        p_captured = board.black_captured
        o_captured = board.white_captured
    else:
        p_captured = board.white_captured
        o_captured = board.black_captured

    score = (p_stones - o_stones) * 3.0
    score += (_go_liberties(board, player) - _go_liberties(board, opponent)) * 1.0
    score += (p_captured - o_captured) * 4.0
    return score
