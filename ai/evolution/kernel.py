# -*- coding: utf-8 -*-
"""
进化类下棋 AI 的内部内核：个体解码、适应度、棋理先验。

本模块对外部不可见。调用方只给棋盘、拿一步棋；「编码方式、对手模型、
先验、适应度」全部在这里闭环，属于算法自身实现。

个体统一为长度 horizon 的实数向量（每个分量 ∈ [0,1)）。解码器把分量
映射成「当前局面候选步列表」的索引，因此 DE / PSO / ABC 的连续算子可以
原样保留，且每一步都取自实时合法候选集，永远不会产生非法着法：
向量 → (我走一步 → 对手应一步) × horizon → 局面评估。
"""

from typing import List, Optional, Tuple

from ai.candidates import (candidate_moves, gomoku_attack_points,
                           gomoku_defense_points, gomoku_forced_move,
                           move_heuristic_score, sort_moves_by_heuristic)
from ai.evaluator import evaluate
from core.base_board import DRAW

WIN_SCORE = 1_000_000.0
VERY_BAD = -1e18
OPPONENT_TOP = 12      # 对手模型只在前 N 个候选内挑，控制单个体评估成本
SEED_TOP = 8           # 启发式先验注入的种子数量上限


def current_candidates(state) -> List[Tuple[int, int]]:
    """当前回合的候选步：优先邻域裁剪结果，为空时退回全部合法步。"""
    cands = candidate_moves(state)
    return cands if cands else state.get_legal_moves()


def _fast_candidates(state):
    """推演中的对手候选：象棋直接用伪合法走法，省掉整盘将军过滤。"""
    if type(state).__name__ == "ChessBoard":
        return state._pseudo_moves(state.current_player)
    return current_candidates(state)


def _fast_apply(state, move):
    """推演落子：棋盘提供 fast_apply 时跳过重复合法性校验。"""
    if hasattr(state, "fast_apply"):
        return state.fast_apply(move)
    return state.apply_move(move)


def _heuristic_reply(state) -> bool:
    """轻量对手模型：取候选中棋理分最高的一步应手（一层贪心近似最优应对）。"""
    cands = _fast_candidates(state)[:OPPONENT_TOP]
    if not cands:
        return False
    mover = state.current_player
    best = max(cands, key=lambda m: move_heuristic_score(state, m, mover))
    return _fast_apply(state, best)


def decode(board, vector, player, horizon):
    """
    把实数向量解码成一条合法推演序列。

    返回 (first_move, final_state, my_steps)：
    first_move 即个体主张的落子点，final_state 用于打分，my_steps 用于
    「越快取胜越好」的终局奖励。
    """
    state = board.copy()
    first: Optional[Tuple[int, int]] = None
    steps = 0

    for j in range(horizon):
        if state.game_over:
            break
        # 规范到我方回合；黑白棋跳回合导致我方无步可走时停止推演
        if state.current_player != player:
            if not state.has_legal_moves(player):
                break
            state.current_player = player

        cands = current_candidates(state)
        if not cands:
            break

        v = vector[j] if j < len(vector) else 0.5
        idx = int(v * len(cands))
        idx = max(0, min(len(cands) - 1, idx))
        move = cands[idx]
        if first is None:
            first = move
        if not _fast_apply(state, move):
            break
        steps += 1
        if state.game_over:
            break
        _heuristic_reply(state)

    return first, state, steps


def fitness(board, vector, player, horizon):
    """适应度：推演终局的胜负奖励，或末局面的启发式评估分（player 视角）。"""
    first, state, steps = decode(board, vector, player, horizon)
    if first is None:
        return VERY_BAD, None

    if state.game_over and state.winner:
        if state.winner == player:
            return WIN_SCORE - steps, first
        if state.winner == DRAW:
            return 0.0, first
        return -WIN_SCORE + steps, first

    return evaluate(state, player), first


def forced_move(board, player):
    """
    强制预检先验：复用与 MCTS / Alpha-Beta 同一份四层战术预检。

    命中时跳过种群搜索，避免战术层面被随机个体带偏——尤其是跳三
    1101 / 1011 补中间空位直接成活四的情形。
    返回 (move, note)；未命中返回 (None, "")。
    """
    result = gomoku_forced_move(board, player)
    return result if result is not None else (None, "")


def prior_vectors(board, player, horizon, rng, count):
    """
    把棋理先验注入初始种群：成四点 / 活三防守点 / 启发式高分候选，
    编码成「第一步指向该点 + 后续随机」的向量，让搜索从好棋起步。
    """
    cands = current_candidates(board)
    if not cands or count <= 0:
        return []

    index = {m: i for i, m in enumerate(cands)}
    strong: List[Tuple[int, int]] = []
    if type(board).__name__ == "GomokuBoard":
        strong += gomoku_attack_points(board, player)
        strong += gomoku_defense_points(board, player)
    strong += sort_moves_by_heuristic(board, cands, player)[:SEED_TOP]

    vectors: List[List[float]] = []
    seen = set()
    for m in strong:
        if len(vectors) >= count or m not in index or m in seen:
            continue
        seen.add(m)
        v = [(index[m] + 0.5) / len(cands)]
        v += [rng.random() for _ in range(horizon - 1)]
        vectors.append(v)
    return vectors
