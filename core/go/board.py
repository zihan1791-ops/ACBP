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

本版本未实现（README 中已注明的课程范围限制）：
    全局劫争循环判定、贴目、双活 / 公活的精确处理、专业数子法。
"""

from typing import List, Tuple, Set, Optional

from core.base_board import BaseBoard, EMPTY, BLACK, WHITE, DRAW


class GoBoard(BaseBoard):
    """围棋棋盘与基础规则状态机。"""

    def __init__(self, size: int = 9) -> None:
        super().__init__(size)
        # 提子计数：black_captured 为黑方提掉的白子总数；white_captured 反之
        self.black_captured = 0
        self.white_captured = 0
        # 打劫禁着点：上一手刚被提走的单颗子位置，下一手禁止落子于此；None 表示无禁着点
        self.ko_point: Optional[Tuple[int, int]] = None

    # -------------------- 规则接口实现 --------------------

    def get_legal_moves(self) -> List[Tuple[int, int]]:
        """返回当前玩家全部合法空位（排除自杀点与打劫禁着点）。"""
        moves: List[Tuple[int, int]] = []
        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] != EMPTY:
                    continue
                if self.ko_point is not None and (r, c) == self.ko_point:
                    continue
                if self._placement_is_legal(r, c, self.current_player)[0]:
                    moves.append((r, c))
        return moves

    def apply_move(self, move: Tuple[int, int]) -> bool:
        """落子、提子并更新打劫禁着点；非法落子返回 False 且状态不变。"""
        row, col = move

        if self.game_over:
            return False
        if not self.in_bounds(row, col):
            return False
        if self.board[row][col] != EMPTY:
            return False
        if self.ko_point is not None and (row, col) == self.ko_point:
            return False

        legal, captured = self._placement_is_legal(row, col, self.current_player)
        if not legal:
            return False

        # 正式落子
        self.board[row][col] = self.current_player

        # 提走所有无气的对方连通块，并累计提子数
        for cr, cc in captured:
            self.board[cr][cc] = EMPTY
        if self.current_player == BLACK:
            self.black_captured += len(captured)
        else:
            self.white_captured += len(captured)

        # 更新打劫禁着点：仅当刚提走对方单颗子时，该位置成为下一手禁着点
        if len(captured) == 1:
            self.ko_point = captured[0]
        else:
            self.ko_point = None

        self.last_move = (row, col)
        self.move_count += 1
        self._record_move(row, col, self.current_player)
        self._swap_player()
        return True

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

    # -------------------- 规则辅助计算 --------------------

    def _collect_group(self, row: int, col: int) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
        """
        从 (row, col) 出发 BFS，收集同色连通块及其全部气（相邻空位）。

        返回：
            group:    连通块内所有棋子坐标集合；
            liberties: 该连通块的气（相邻空位坐标集合）。
        """
        color = self.board[row][col]
        group: Set[Tuple[int, int]] = set()
        liberties: Set[Tuple[int, int]] = set()
        queue: List[Tuple[int, int]] = [(row, col)]
        group.add((row, col))

        # 围棋的气只看上下左右四个正交方向，不看斜向
        orthogonal = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        while queue:
            r, c = queue.pop()
            for dr, dc in orthogonal:
                nr, nc = r + dr, c + dc
                if not self.in_bounds(nr, nc):
                    continue
                if self.board[nr][nc] == EMPTY:
                    liberties.add((nr, nc))
                elif self.board[nr][nc] == color and (nr, nc) not in group:
                    group.add((nr, nc))
                    queue.append((nr, nc))
        return group, liberties

    def _placement_is_legal(self, row: int, col: int, player: int
                             ) -> Tuple[bool, List[Tuple[int, int]]]:
        """
        试探性判断在 (row, col) 落子是否合法。

        返回：
            (是否合法, 落子后将被提走的对方棋子坐标列表)
        该方法不修改棋盘最终状态；仅在内部临时落子后回滚。
        """
        opponent = self.opponent(player)

        # 临时落子
        self.board[row][col] = player
        captured: List[Tuple[int, int]] = []

        # 检查四个正交相邻方向上的对方连通块，收集无气者
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = row + dr, col + dc
            if not self.in_bounds(nr, nc) or self.board[nr][nc] != opponent:
                continue
            group, liberties = self._collect_group(nr, nc)
            if not liberties:
                captured.extend(group)

        # 检查己方连通块是否还有气
        _, my_liberties = self._collect_group(row, col)

        # 自杀判定：己方无气且没有提走对方棋子 → 非法，回滚
        legal = bool(my_liberties) or bool(captured)

        # 撤销临时落子（被提子此时尚未真正从棋盘移除，无需恢复）
        self.board[row][col] = EMPTY
        return legal, captured

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
        black = white = 0
        for row in self.board:
            for cell in row:
                if cell == BLACK:
                    black += 1
                elif cell == WHITE:
                    white += 1
        return black, white
