# -*- coding: utf-8 -*-
"""
批量局面评估：把一批棋盘堆成 (B, H, W) 张量一次打分。

后端优先级：torch + CUDA（可选 GPU）→ numpy（CPU 向量化）→ None（调用方
回退逐局面 evaluator）。**没有任何强制依赖**：numpy / torch 都是延迟导入，
未安装时本模块直接返回 None，不装也能跑全部算法。

评分为「位置权重加权和 + 四方向连子奖励」，用于种群内相对排序；
与逐局面 evaluator 的绝对分值不必完全相等，但单调趋势一致。
"""

from typing import List, Optional

_DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))
_CHESS_VALUE = {1: 10000, 2: 200, 3: 200, 4: 400, 5: 900, 6: 450, 7: 100}
_LINE_WEIGHT = 0.35


def _numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


def gpu_available() -> bool:
    """延迟探测 CUDA；未装 torch 或无 GPU 一律返回 False。"""
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def backend_name() -> str:
    np = _numpy()
    if np is None:
        return "cpu"
    return "cuda" if gpu_available() else "numpy"


def _shape(board):
    if type(board).__name__ == "ChessBoard":
        return board.rows, board.cols
    return board.size, board.size


def _weights(np, kind: str, rows: int, cols: int):
    if kind == "OthelloBoard":
        try:
            from ai.evaluator import _OTHELLO_WEIGHTS
            return np.asarray(_OTHELLO_WEIGHTS, dtype=np.float32) / 120.0
        except Exception:
            pass
    yy, xx = np.mgrid[0:rows, 0:cols]
    cy, cx = (rows - 1) / 2.0, (cols - 1) / 2.0
    if kind == "ChessBoard":
        # 象棋中路更重要，纵向差异弱化
        return (1.0 - np.abs(xx - cx) / max(1.0, cx)).astype(np.float32)
    dist = np.sqrt(((yy - cy) / max(1.0, rows / 2)) ** 2
                   + ((xx - cx) / max(1.0, cols / 2)) ** 2)
    return (1.0 - dist / 1.5).astype(np.float32)


def _encode(np, board, player, rows: int, cols: int):
    out = np.zeros((rows, cols), dtype=np.float32)
    chess = type(board).__name__ == "ChessBoard"
    for r in range(rows):
        row = board.board[r]
        for c in range(cols):
            cell = row[c]
            if not cell:
                continue
            if chess:
                side, kind = cell // 10, cell % 10
                value = _CHESS_VALUE.get(kind, 100) / 1000.0
                out[r, c] = value if side == player else -value
            else:
                out[r, c] = 1.0 if cell == player else -1.0
    return out


def batch_scores(boards, player, prefer_gpu: bool = True) -> Optional[List[float]]:
    """返回与 boards 等长的分数列表；后端不可用时返回 None。"""
    np = _numpy()
    if np is None or not boards:
        return None
    rows, cols = _shape(boards[0])
    kind = type(boards[0]).__name__
    same = all(_shape(b) == (rows, cols) and type(b).__name__ == kind
               for b in boards)
    if not same:
        return None

    data = np.stack([_encode(np, b, player, rows, cols) for b in boards])
    w = _weights(np, kind, rows, cols)

    if prefer_gpu and gpu_available():
        try:
            import torch
            device = "cuda"
            t = torch.as_tensor(data, dtype=torch.float32, device=device)
            tw = torch.as_tensor(w, dtype=torch.float32, device=device)
            score = (t * tw).sum(dim=(1, 2))
            line = torch.zeros_like(score)
            for dr, dc in _DIRS:
                shifted = torch.roll(t, shifts=(dr, dc), dims=(1, 2))
                line = line + (t * shifted).sum(dim=(1, 2))
            return (score + _LINE_WEIGHT * line).detach().cpu().numpy().tolist()
        except Exception:
            pass  # CUDA 异常一律回退 numpy，不影响对局

    score = (data * w).sum(axis=(1, 2))
    line = np.zeros(len(boards), dtype=np.float32)
    for dr, dc in _DIRS:
        shifted = np.roll(data, shift=(dr, dc), axis=(1, 2))
        line = line + (data * shifted).sum(axis=(1, 2))
    return (score + _LINE_WEIGHT * line).astype(np.float64).tolist()
