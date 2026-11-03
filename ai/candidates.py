# -*- coding: utf-8 -*-
"""
AI 候选走法裁剪与启发式评分。

作用：
1. candidate_moves —— 把「全盘所有空位」裁剪为「已有棋子邻域内的空位」，
   大幅缩小搜索分支因子（五子棋 225 → 约 40~80 个候选），是搜索变强的关键；
2. gomoku_winning_moves —— 找出「下一手直接连成五子」的落点，供 AI 强制
   进攻 / 防守兜底；
3. move_heuristic_score —— 给单个候选步打「棋理分」，用于走法排序（Alpha-Beta
   优先搜索高价值分支、更快触发剪枝）与 MCTS 扩展 / 模拟的启发式选步。

本模块只依赖规则层与 evaluator 的纯棋型打分，不依赖 pygame。
"""

from typing import List, Tuple

from core.base_board import EMPTY
from ai.evaluator import _pattern_score, _GOMOKU_DIRS, _OTHELLO_WEIGHTS

# 邻域裁剪半径（格）：离已有棋子多远仍视为「相关候选」
CANDIDATE_RADIUS = 2


def is_near_stone(board, move: Tuple[int, int], radius: int = 1) -> bool:
    """判断 move 是否落在已有棋子 radius 格邻域内。"""
    r, c = move
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if board.in_bounds(nr, nc) and board.board[nr][nc] != EMPTY:
                return True
    return False


def candidate_moves(board) -> List[Tuple[int, int]]:
    """
    返回当前玩家应优先搜索的候选走法列表。

    - 黑白棋：合法步天然很少，直接返回全部合法步（不做裁剪）；
    - 五子棋：只返回已有棋子 2 格邻域内的空位；棋盘为空时返回中心附近点位；
    - 围棋（规则代码保留）：同样采用邻域裁剪。
    """
    legal = board.get_legal_moves()
    if not legal:
        return []

    kind = type(board).__name__
    if kind == "OthelloBoard":
        return legal

    # 棋盘尚无棋子：五子棋落在中心附近即可，围棋同理
    stones = [(r, c) for r in range(board.size)
              for c in range(board.size) if board.board[r][c] != EMPTY]
    if not stones:
        mid = board.size // 2
        if kind == "GomokuBoard":
            return [(mid, mid), (mid - 1, mid - 1), (mid - 1, mid), (mid, mid - 1)]
        return [(mid, mid)]

    # 邻域裁剪：收集已有棋子 CANDIDATE_RADIUS 格内的空位
    cand: set = set()
    for r, c in stones:
        for dr in range(-CANDIDATE_RADIUS, CANDIDATE_RADIUS + 1):
            for dc in range(-CANDIDATE_RADIUS, CANDIDATE_RADIUS + 1):
                nr, nc = r + dr, c + dc
                if board.in_bounds(nr, nc) and board.board[nr][nc] == EMPTY:
                    cand.add((nr, nc))

    # 兜底：若裁剪结果为空（理论不发生），退回全部合法步
    result = [m for m in legal if m in cand]
    return result or legal


def gomoku_winning_moves(board, player: int) -> List[Tuple[int, int]]:
    """
    找出 player 下一手落子即可连成五子的全部位置（五子棋专用）。

    原理：在副本的棋格上临时放置一枚 player 棋子，用规则层的连子统计
    判断是否达到五连；检查后立即恢复空位，不改变棋盘状态。
    """
    moves: List[Tuple[int, int]] = []
    if type(board).__name__ != "GomokuBoard":
        return moves

    for r in range(board.size):
        for c in range(board.size):
            if board.board[r][c] != EMPTY:
                continue
            # 临时落子（不经过 apply_move，避免副作用）
            board.board[r][c] = player
            if board._count_line(r, c, player) >= 5:
                moves.append((r, c))
            board.board[r][c] = EMPTY
    return moves


def gomoku_attack_points(board, player: int) -> List[Tuple[int, int]]:
    """
    五子棋进攻成四点：player 落子后能立即形成「活四」（双端开放的 4 连）
    的全部位置。

    用途：己方活三存在时，先手成活四必胜（对手必须防守，否则下一步五连），
    进攻价值高于被动堵对手活三。用棋型分判定：活四 12000 分；冲四 1500
    分只是单端威胁（对手可堵死），不视为必胜进攻点。
    """
    points: List[Tuple[int, int]] = []
    if type(board).__name__ != "GomokuBoard":
        return points

    for r in range(board.size):
        for c in range(board.size):
            if board.board[r][c] != EMPTY:
                continue
            if _gomoku_point_score(board, r, c, player) >= 12000:
                points.append((r, c))
    return points


def gomoku_defense_points(board, defender: int) -> List[Tuple[int, int]]:
    """
    五子棋软性防守点：对手「活三 / 冲三 / 跳三」威胁的开放两端。

    覆盖成五预检之外的早期威胁：对手三连若不及时堵端，下一步即成
    活四 / 冲四，再下一步必胜。返回的端点用于候选排序前置与 rollout
    战术优先，属于「强优先」而非「绝对强制」。

    支持两类三连威胁：
    1. 连续三连（XXX，两端皆空）——经典活三；
    2. 跳三（X_XX / XX_X，4 格内 3 子 1 空、两端皆空）——跳活三，
       补中间空位即成连续活四，威胁等级与连活三一致；
    四连及以上由 gomoku_winning_moves 的强制预检处理。
    """
    points: List[Tuple[int, int]] = []
    if type(board).__name__ != "GomokuBoard":
        return points

    opponent = board.opponent(defender)
    seen: set = set()

    for r in range(board.size):
        for c in range(board.size):
            if board.board[r][c] != opponent:
                continue
            for dr, dc in _GOMOKU_DIRS:
                # 只统计起点恰为段首的完整段（避免同段重复扫描）
                br, bc = r - dr, c - dc
                if board.in_bounds(br, bc) and board.board[br][bc] == opponent:
                    continue

                # 沿该方向数出 opponent 的连续段
                count = 0
                rr, cc = r, c
                while (board.in_bounds(rr, cc)
                       and board.board[rr][cc] == opponent):
                    count += 1
                    rr += dr
                    cc += dc
                if count > 3:
                    continue  # 四连及以上交给成五强制层

                # 段尾（第一个非 opponent 格）必须为空，否则被堵
                if not board.in_bounds(rr, cc) or board.board[rr][cc] != EMPTY:
                    continue

                # 跳子检测：段尾空位后是否紧跟 opponent 子（跳三形态）
                jr, jc = rr + dr, cc + dc
                jcount = 0
                while (board.in_bounds(jr, jc)
                       and board.board[jr][jc] == opponent):
                    jcount += 1
                    jr += dr
                    jc += dc

                # 总子数必须为 3：count==3（连续活三）或 count+跳子==3（跳三）
                if count + jcount != 3:
                    continue

                # 两端必须为空：段首前 + 段尾（无跳子时）或跳子后
                end1 = (r - dr, c - dc)
                end2 = (rr, cc) if jcount == 0 else (jr, jc)
                if (board.in_bounds(*end1)
                        and board.board[end1[0]][end1[1]] == EMPTY
                        and board.in_bounds(*end2)
                        and board.board[end2[0]][end2[1]] == EMPTY):
                    for pt in (end1, end2):
                        if pt not in seen:
                            seen.add(pt)
                            points.append(pt)
    return points


def _gomoku_point_score(board, r: int, c: int, player: int) -> int:
    """
    计算 player 若在 (r, c) 落子后，能形成的最大四方向棋型分。

    只做临时落子 + 恢复，不改变棋盘最终状态。
    """
    board.board[r][c] = player
    best = 0
    for dr, dc in _GOMOKU_DIRS:
        # 统计以 (r, c) 为中心、沿 (dr, dc) 方向的连续段与开放端
        count = 1
        open_ends = 0
        # 正方向延伸
        rr, cc = r + dr, c + dc
        while board.in_bounds(rr, cc) and board.board[rr][cc] == player:
            count += 1
            rr += dr
            cc += dc
        if not board.in_bounds(rr, cc) or board.board[rr][cc] == EMPTY:
            open_ends += 1
        # 反方向延伸
        rr, cc = r - dr, c - dc
        while board.in_bounds(rr, cc) and board.board[rr][cc] == player:
            count += 1
            rr -= dr
            cc -= dc
        if not board.in_bounds(rr, cc) or board.board[rr][cc] == EMPTY:
            open_ends += 1
        best = max(best, _pattern_score(count, open_ends))
    board.board[r][c] = EMPTY
    return best


def move_heuristic_score(board, move: Tuple[int, int], player: int) -> float:
    """
    给候选步 move 打棋理分（以将要落子方 player 视角）：

    - 五子棋：己方在此落子形成的最大棋型分 + 对手若在此落子形成的棋型分
      （防守价值，权重稍高），再加邻域位置小奖励；
    - 黑白棋：直接使用位置权重表（角 > 边 > 中心）。
    分值仅供排序与加权随机使用，不参与终局判定。
    """
    r, c = move
    kind = type(board).__name__

    if kind == "OthelloBoard":
        if board.in_bounds(r, c):
            return float(_OTHELLO_WEIGHTS[r][c])
        return 0.0

    if kind == "GomokuBoard":
        opponent = board.opponent(player)
        attack = _gomoku_point_score(board, r, c, player)
        defend = _gomoku_point_score(board, r, c, opponent)
        near = 4.0 if is_near_stone(board, (r, c)) else 0.0
        return float(attack) + defend * 1.3 + near

    # 其它棋种（围棋等）：邻域优先即可
    return 4.0 if is_near_stone(board, (r, c)) else 0.0


def sort_moves_by_heuristic(board, moves: List[Tuple[int, int]],
                            player: int) -> List[Tuple[int, int]]:
    """按启发式评分从高到低排序候选走法（评分高的优先搜索 / 优先扩展）。"""
    return sorted(moves, key=lambda m: -move_heuristic_score(board, m, player))
