# -*- coding: utf-8 -*-
"""
围棋（Go）规则实现 —— 课程作业基础版本。

已实现规则：
1. 黑棋先行，在交叉点空位落子；
2. 气的计算：与棋子上下左右相连的空位称为「气」；
3. 提子：落子后相邻对方连通块若没有气，则被全部提走；
4. 自杀禁着：落子后己方连通块没有气、且没有提走对方棋子时，禁止落子；
5. 简单打劫：禁止一手棋立即把上一手刚被提走的单颗子重新提回；
6. 终局由玩家在界面点击「结束对局」触发，按「棋子 + 包围区域」简化数子判定胜负。

性能设计（本轮改造）：
    原先每个候选点都要用 set / BFS 试探性落子、收集连通块与气，19 路棋盘
    下代价很高（实测 9 路中盘合法步生成 0.17ms，19 路更贵）。现在改为位板
    连通块：整数「或 / 与」扩张求整块，再与空位板相交求气；一次合法步生成
    只构建一次位板，逐候选点复用。二维列表仍是权威表示，试探不再写棋盘。

    另提供 push/pop：搜索推演原地落子 + 回溯，额外保存提子数与打劫禁着点。

本版本未实现（README 中已注明的课程范围限制）：
    全局劫争循环判定、贴目、双活 / 公活的精确处理、专业数子法。
"""

from typing import List, Tuple, Set, Optional

from core.base_board import BaseBoard, EMPTY, BLACK, WHITE, DRAW
from core.bitboard import iter_bits, bit_count


class GoBoard(BaseBoard):
    """围棋棋盘与基础规则状态机。"""

    def __init__(self, size: int = 9) -> None:
        super().__init__(size)
        # 提子计数：black_captured 为黑方提掉的白子总数；white_captured 反之
        self.black_captured = 0
        self.white_captured = 0
        # 打劫禁着点：上一手刚被提走的单颗子位置，下一手禁止落子于此；None 表示无禁着点
        self.ko_point: Optional[Tuple[int, int]] = None

    # -------------------- 位板上下文 --------------------

    def _go_ctx(self):
        """(geometry, {取值: 位板}, occupied, empty)：一次构建，整轮复用。"""
        geo, masks = self._bitboards()
        occupied = masks[BLACK] | masks[WHITE]
        return geo, masks, occupied, geo.full ^ occupied

    # -------------------- 规则接口实现 --------------------

    def get_legal_moves(self) -> List[Tuple[int, int]]:
        """返回当前玩家全部合法空位（排除自杀点与打劫禁着点）。"""
        geo, masks, occupied, empty = self._go_ctx()
        player = self.current_player
        ko_bit = (1 << (self.ko_point[0] * self.size + self.ko_point[1])) \
            if self.ko_point is not None else 0
        moves: List[Tuple[int, int]] = []
        # 只遍历空位所在的位，不再逐格判断是否为空格
        for idx in iter_bits(empty & ~ko_bit):
            row, col = divmod(idx, self.size)
            if self._placement_is_legal(row, col, player,
                                        (geo, masks, occupied, empty))[0]:
                moves.append((row, col))
        return moves

    def _placement_is_legal(self, row: int, col: int, player: int,
                            ctx=None) -> Tuple[bool, List[Tuple[int, int]]]:
        """
        位板版试探：返回 (是否合法, 落子后将被提走的对方棋子坐标列表)。

        不修改棋盘，也就不会破坏二维列表与位板的一致性。逻辑顺序：
            1. 逻辑上落子 → 得到 occupied / empty；
            2. 四个相邻方向上的对方连通块，无气者整块计入 captured；
            3. 提子后重新求己方所在块的气，有气或提了子才合法（自杀禁着）。
        """
        if ctx is None:
            ctx = self._go_ctx()
        geo, masks, occupied, empty = ctx
        idx = row * self.size + col
        place = 1 << idx
        opponent = self.opponent(player)
        opp_mask = masks[opponent]
        my_mask = masks[player] | place
        occ_after = occupied | place
        empty_after = empty & ~place

        captured = 0
        seen = 0
        for ni in iter_bits(geo.neighbor_mask[idx] & opp_mask):
            if (seen >> ni) & 1:
                continue
            group, libs = geo.group(opp_mask, ni)
            seen |= group
            if not (libs & empty_after):
                captured |= group

        occ_final = occ_after & ~captured
        empty_final = geo.full ^ occ_final
        _, my_libs = geo.group(my_mask, idx)
        legal = bool(my_libs & empty_final) or bool(captured)
        return legal, geo.cells_of(captured) if captured else []

    def _apply_core(self, row: int, col: int, captured) -> None:
        """落子 + 提子 + 打劫 / 计数更新（不含合法性校验）。"""
        player = self.current_player
        self.board[row][col] = player
        for cr, cc in captured:
            self.board[cr][cc] = EMPTY
        if player == BLACK:
            self.black_captured += len(captured)
        else:
            self.white_captured += len(captured)

        if len(captured) == 1:
            self.ko_point = captured[0]
        else:
            self.ko_point = None

        self.last_move = (row, col)
        self.move_count += 1
        self._record_move(row, col, player)
        self._swap_player()

    def _apply_unchecked(self, move) -> bool:
        """push() 用：调用方保证 move 合法；提子计算仍须按规则执行。"""
        row, col = move
        if self.game_over or not self.in_bounds(row, col):
            return False
        if self.board[row][col] != EMPTY:
            return False
        if self.ko_point is not None and (row, col) == self.ko_point:
            return False
        legal, captured = self._placement_is_legal(row, col, self.current_player)
        if not legal:
            return False
        self._apply_core(row, col, captured)
        return True

    def apply_move(self, move: Tuple[int, int]) -> bool:
        """落子、提子并更新打劫禁着点；非法落子返回 False 且状态不变。"""
        return self._apply_unchecked(move)

    def _check_game_end(self) -> None:
        """围棋不自动判定终局；终局由 end_game_manually() 手动触发。"""
        return

    def end_game_manually(self) -> None:
        """
        玩家主动结束对局：执行简化数子并写入 winner。

        简化口径：区域只被一种颜色包围则计入该方；同时接触黑白两色的空位
        视为中立区域，不计分；本版本不计算贴目。
        """
        black_score, white_score = self.score_territory()
        self.game_over = True
        if black_score > white_score:
            self.winner = BLACK
        elif white_score > black_score:
            self.winner = WHITE
        else:
            self.winner = DRAW

    def copy(self) -> "GoBoard":
        """深拷贝当前棋盘状态（含提子数与打劫禁着点），供 AI 搜索推演。"""
        new_board = GoBoard(self.size)
        self._base_copy_state(new_board)
        new_board.black_captured = self.black_captured
        new_board.white_captured = self.white_captured
        new_board.ko_point = self.ko_point
        return new_board

    # -------------------- push/pop 额外状态 --------------------

    def _snapshot(self) -> tuple:
        return super()._snapshot() + (self.black_captured,
                                      self.white_captured, self.ko_point)

    def _restore(self, snap: tuple) -> None:
        super()._restore(snap)
        self.black_captured = snap[7]
        self.white_captured = snap[8]
        self.ko_point = snap[9]

    # -------------------- 规则辅助计算 --------------------

    def _collect_group(self, row: int, col: int) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
        """
        从 (row, col) 出发求同色连通块及其气；位板版，供外部 / 测试调用。

        返回 (连通块坐标集合, 气的坐标集合)，与旧 set-BFS 实现语义一致。
        """
        color = self.board[row][col]
        if color == EMPTY:
            return set(), set()
        geo, masks, occupied, empty = self._go_ctx()
        idx = row * self.size + col
        group, libs = geo.group(masks[color], idx)
        return set(geo.cells_of(group)), set(geo.cells_of(libs & empty))

    def score_territory(self) -> Tuple[float, float]:
        """
        简化数子：返回 (黑方得分, 白方得分)。

        得分 = 己方棋子数 + 己方单独包围的空位区域；
        同时接触黑白两色的空位为中立区域，不计入任何一方。
        """
        black_stones, white_stones = self.count_pieces()
        visited: Set[Tuple[int, int]] = set()
        black_area = white_area = 0

        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] != EMPTY or (r, c) in visited:
                    continue
                # BFS 遍历一片连通空位区域
                region: List[Tuple[int, int]] = []
                boundary: Set[int] = set()
                queue: List[Tuple[int, int]] = [(r, c)]
                visited.add((r, c))
                while queue:
                    cr, cc = queue.pop()
                    region.append((cr, cc))
                    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nr, nc = cr + dr, cc + dc
                        if not self.in_bounds(nr, nc):
                            continue
                        if self.board[nr][nc] == EMPTY and (nr, nc) not in visited:
                            visited.add((nr, nc))
                            queue.append((nr, nc))
                        elif self.board[nr][nc] != EMPTY:
                            boundary.add(self.board[nr][nc])

                # 区域只接触一种颜色时，整片区域计入该方
                if boundary == {BLACK}:
                    black_area += len(region)
                elif boundary == {WHITE}:
                    white_area += len(region)

        return black_stones + black_area, white_stones + white_area

    def count_pieces(self) -> Tuple[int, int]:
        """统计黑、白棋子数量，返回 (黑棋数, 白棋数)。"""
        _, masks = self._bitboards()
        return bit_count(masks[BLACK]), bit_count(masks[WHITE])
