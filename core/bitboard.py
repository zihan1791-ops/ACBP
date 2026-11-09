# -*- coding: utf-8 -*-
"""
位板（bitboard）工具层 —— 把棋盘格子映射到一个大整数的各个二进制位。

设计取舍（重要）：
    本项目 UI、棋谱、评估函数、历史遗留测试都直接读写二维列表 `board.board`，
    且存在「试探性落子 → 读 → 立刻还原」的写法（ai/candidates.py、ai/mcts.py）。
    若把位板做成需要双向同步的持久状态，这些直接写入会让位板悄悄失同步，
    进而产生难以复现的非法着法。

    因此这里把**二维列表继续作为权威表示**，位板作为规则计算时的加速结构：
    每次代价较高的一次规则计算（合法步生成 / 将军探测 / 气计算）开始时，
    用 `_bitboards()` 从二维列表一次性构建，然后整轮热点全部走位运算 / 位扫描。
    构建成本 O(格子数) 的整数循环，远低于原先的二维列表 + 对象分配开销，
    同时外部任何直接修改都天然生效，不需要 refresh()。

对外提供：
    BitboardGeometry  —— 尺寸相关的预计算表（射线、四邻、方向移位、边界掩码）
    iter_bits / bit_count / cells_of —— 位集合工具
    build_bitboards   —— 从二维列表构建 (occ, mine, opp) 或按取值分组的位板
"""

from typing import Dict, Iterator, List, Tuple

# 八个方向（dr, dc），与 core.base_board.ALL_DIRECTIONS 保持一致
DIRECTIONS_8: Tuple[Tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)
DIRECTIONS_4: Tuple[Tuple[int, int], ...] = (
    (-1, 0), (1, 0), (0, -1), (0, 1),
)


def iter_bits(mask: int) -> Iterator[int]:
    """按低位到高位逐个产出置位的位索引；比反复扫二维列表快。"""
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def bit_count(mask: int) -> int:
    """Python 3.8/3.10 兼容的 popcount。"""
    return mask.bit_count() if hasattr(mask, "bit_count") else bin(mask).count("1")


class BitboardGeometry:
    """
    某个 (rows, cols) 棋盘的尺寸相关预计算表。

    采用「行优先」位编号：idx = row * cols + col。
    Python 整数没有位数上限，19 路围棋 (361 位) 与 10×9 象棋 (90 位) 都适用。
    """

    _CACHE: Dict[Tuple[int, int], "BitboardGeometry"] = {}

    def __new__(cls, rows: int, cols: int) -> "BitboardGeometry":
        key = (rows, cols)
        obj = cls._CACHE.get(key)
        if obj is None:
            obj = super().__new__(cls)
            obj._init(key)
            cls._CACHE[key] = obj
        return obj

    def _init(self, key: Tuple[int, int]) -> None:
        rows, cols = key
        self.rows, self.cols = rows, cols
        self.cell_count = rows * cols
        self.full = (1 << self.cell_count) - 1

        left = 0
        right = 0
        for r in range(rows):
            left |= 1 << (r * cols)
            right |= 1 << (r * cols + cols - 1)
        self.left_col = left
        self.right_col = right
        self.not_left_col = self.full ^ left
        self.not_right_col = self.full ^ right

        # 四邻扩张表：neighbor_mask[idx] 是 idx 的上下左右邻居位集合
        neighbors: List[int] = []
        rays: Dict[Tuple[int, int, int], Tuple[int, ...]] = {}
        for idx in range(self.cell_count):
            r, c = divmod(idx, cols)
            n = 0
            for dr, dc in DIRECTIONS_4:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    n |= 1 << (nr * cols + nc)
            neighbors.append(n)
            for dr, dc in DIRECTIONS_8:
                seq: List[int] = []
                nr, nc = r + dr, c + dc
                while 0 <= nr < rows and 0 <= nc < cols:
                    seq.append(nr * cols + nc)
                    nr += dr
                    nc += dc
                rays[(idx, dr, dc)] = tuple(seq)
        self.neighbor_mask = tuple(neighbors)
        self.rays = rays

    # -------------------- 基础换算 --------------------

    def bit(self, row: int, col: int) -> int:
        return 1 << (row * self.cols + col)

    def index(self, row: int, col: int) -> int:
        return row * self.cols + col

    def cell(self, idx: int) -> Tuple[int, int]:
        return divmod(idx, self.cols)

    def cells_of(self, mask: int) -> List[Tuple[int, int]]:
        """位集合 → (row, col) 列表，用于把位运算结果交回二维列表契约。"""
        cols = self.cols
        return [divmod(i, cols) for i in iter_bits(mask)]

    def ray(self, idx: int, dr: int, dc: int) -> Tuple[int, ...]:
        """从 idx 出发沿 (dr, dc) 的射线位索引，按距离由近到远排列。"""
        return self.rays.get((idx, dr, dc), ())

    # -------------------- 方向移位（带防串列保护） --------------------

    def shift(self, mask: int, dr: int, dc: int) -> int:
        """
        把整个位集合沿 (dr, dc) 平移一格；左/右移位会先屏蔽边界列，
        避免第 0 列与最后一列互相「绕回」到相邻行。
        """
        if dc < 0:
            mask = (mask & self.not_left_col) >> (-dc)
        elif dc > 0:
            mask = (mask & self.not_right_col) << dc
        if dr > 0:
            mask = (mask << (dr * self.cols)) & self.full
        elif dr < 0:
            mask = mask >> (-dr * self.cols)
        return mask & self.full

    def expand4(self, mask: int) -> int:
        """
        位集合的上下左右四邻并集 —— 纯整数位移，零 Python 循环。

        左右移位前先屏蔽第 0 列 / 最后一列，防止「绕回」到相邻行；
        上下用整行位移，越界部分由 & full 自然截断。
        """
        cols = self.cols
        return (((mask >> cols) | (mask << cols)
                 | ((mask & self.not_left_col) >> 1)
                 | ((mask & self.not_right_col) << 1)) & self.full)

    def group(self, color_mask: int, start: int) -> Tuple[int, int]:
        """
        位板连通块：返回 (连通块位集合, 该块的四邻位集合)。

        用整数 flood fill 反复扩张直到收敛，替代 set/BFS 与逐位查表；
        气位集合由调用方与 empty 位板相交得到。
        """
        group = 1 << start
        while True:
            grown = (group | self.expand4(group)) & color_mask
            if grown == group:
                break
            group = grown
        return group, self.expand4(group)

    def group_liberties(self, color_mask: int, start: int,
                        empty_mask: int) -> Tuple[int, int]:
        """带空位掩码的连通块：返回 (连通块, 气)。"""
        group, libs = self.group(color_mask, start)
        return group, libs & empty_mask


def build_masks(board_rows, rows: int, cols: int,
                values=(0, 1, 2)) -> Tuple["BitboardGeometry", Dict[int, int]]:
    """
    从二维列表构建「取值 → 位板」映射，一次性 O(格子数) 的整数循环。

    rows/cols 单独传参，因为中国象棋是 10×9 的非方形棋盘。
    返回 (geometry, {取值: 位板})；occupied 由调用方用
    `masks[BLACK] | masks[WHITE]` 得到，empty 用 `geo.full ^ occupied`。
    """
    geo = BitboardGeometry(rows, cols)
    masks = {v: 0 for v in values}
    bit = 1
    for row in board_rows:
        for cell in row:
            target = masks.get(cell)
            if target is not None:
                masks[cell] = target | bit
            bit <<= 1
    return geo, masks
