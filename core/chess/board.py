# -*- coding: utf-8 -*-
"""
中国象棋规则实现（9 列 × 10 行，红方先手）。

棋子编码：cell = side * 10 + kind，side 复用 BaseBoard 的 BLACK(1)/WHITE(2)，
即 1=红方(先手)、2=黑方(后手)；kind: 1 将帅 / 2 士仕 / 3 象相 /
4 马 / 5 车 / 6 炮 / 7 卒兵。0 表示空位。

走法统一用二元组 (from_idx, to_idx)，idx = row * 9 + col，
与项目其它棋种「move 是二元组整数」的契约完全一致：
AI 层、棋谱、ThinkState、控制器均无需区分棋种。

性能设计（本轮改造）：
    二维列表 board 仍是权威表示（UI / 棋谱 / 评估 / 试探性落子都直接读它）。
    每次合法步生成 / 将军探测时，用 _bitboards() 一次性构建位板，整轮热点
    全部走位运算：
      · 棋子遍历改为扫描 side 位板（16 枚棋子，而非 90 个格子）；
      · _in_check 从「枚举对手全部伪合法步」改为「从将位反向探测」——
        车炮按射线找第一/第二个挡子、马反查 8 个来源位与马腿、兵反查
        前进格与过河横吃格，复杂度从 O(棋子数 × 走法数) 降到 O(射线长度)；
      · _try_move_bb 在试走时同步更新位板，整轮只构建一次；
      · 合法步缓存 key 用位板整数元组，替代嵌套 tuple(board) 构造。
    这样外部直接写 board.board 也天然生效，不存在位板失同步问题。

另提供 push/pop（make/unmake）：搜索推演原地落子 + 回溯，省掉 copy() 与
重复的合法性校验。

已实现：九宫、蹩马腿、塞象眼、炮架、过河兵、将帅照面、将军过滤、
将死 / 困毙终局判定，以及「禁止连续重复走法」（长打须变着的简化口径：
同一方连续 3 次走相同 / 原路返回的着法时，该重复着法被禁止）。
未实现（课程范围）：完整的长将 / 长捉判定、三次重复局面判和、
60 回合自然限着。
"""

from typing import List, Tuple, Optional

from core.base_board import BaseBoard, EMPTY, BLACK, WHITE
from core.bitboard import BitboardGeometry, iter_bits

ROWS, COLS = 10, 9

KING, ADVISOR, ELEPHANT, HORSE, ROOK, CANNON, PAWN = 1, 2, 3, 4, 5, 6, 7
_ALL_KINDS = (KING, ADVISOR, ELEPHANT, HORSE, ROOK, CANNON, PAWN)

# 「禁止连续重复走法」（长打须变着的简化口径）：同一方连续走出相同走法，
# 或把刚走的那枚棋子原路走回，累计达到该次数后该走法被禁止。
# 允许一次来回试探（streak 1→2），第三次重复时要求变着。
REPEAT_LIMIT = 3

_RED_NAMES = {KING: "帅", ADVISOR: "仕", ELEPHANT: "相",
              HORSE: "马", ROOK: "车", CANNON: "炮", PAWN: "兵"}
_BLACK_NAMES = {KING: "将", ADVISOR: "士", ELEPHANT: "象",
                HORSE: "马", ROOK: "车", CANNON: "炮", PAWN: "卒"}

_ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
_DIAG = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
_HORSE_STEPS = [(1, 2), (2, 1), (-1, 2), (-2, 1),
                (1, -2), (2, -1), (-1, -2), (-2, -1)]
_ELEPHANT_STEPS = [(2, 2), (2, -2), (-2, 2), (-2, -2)]


def encode_sq(row: int, col: int) -> int:
    return row * COLS + col


def decode_sq(idx: int) -> Tuple[int, int]:
    return divmod(idx, COLS)


def piece_side(cell: int) -> int:
    """从棋子编码取阵营；空格返回 EMPTY。"""
    return cell // 10 if cell else EMPTY


def piece_kind(cell: int) -> int:
    return cell % 10 if cell else EMPTY


def piece_name(cell: int) -> str:
    if not cell:
        return ""
    side, kind = piece_side(cell), piece_kind(cell)
    table = _RED_NAMES if side == BLACK else _BLACK_NAMES
    return table.get(kind, "")


def _piece(side: int, kind: int) -> int:
    return side * 10 + kind


class _Bitboards:
    """一次规则计算内复用的可变位板上下文（__slots__ 避免 dict 开销）。"""

    __slots__ = ("geo", "side", "kind", "occ")

    def __init__(self, geo, side, kind):
        self.geo = geo
        self.side = side          # {BLACK: 位板, WHITE: 位板}
        self.kind = kind          # {兵种: 位板}，不分阵营
        self.occ = side[BLACK] | side[WHITE]

    def cache_key(self, player: int) -> tuple:
        return (player, self.side[BLACK], self.side[WHITE],
                *(self.kind[k] for k in _ALL_KINDS))


class ChessBoard(BaseBoard):
    """中国象棋棋盘与规则状态机。"""

    def __init__(self, size: int = ROWS) -> None:
        super().__init__(ROWS)
        self.rows, self.cols = ROWS, COLS
        self.board = [[EMPTY for _ in range(COLS)] for _ in range(ROWS)]
        self._init_pieces()
        # 同一局面的合法步缓存：将军过滤很贵，搜索中重复局面极多
        self._legal_cache = {}
        # 禁止连续重复走法：每方上一手 + 连续重复计数
        self._last_own_move = {BLACK: None, WHITE: None}
        self._repeat_streak = {BLACK: 0, WHITE: 0}

    def _init_pieces(self) -> None:
        back = [ROOK, HORSE, ELEPHANT, ADVISOR, KING,
                ADVISOR, ELEPHANT, HORSE, ROOK]
        for col, kind in enumerate(back):
            self.board[0][col] = _piece(WHITE, kind)
            self.board[9][col] = _piece(BLACK, kind)
        for col in (1, 7):
            self.board[2][col] = _piece(WHITE, CANNON)
            self.board[7][col] = _piece(BLACK, CANNON)
        for col in (0, 2, 4, 6, 8):
            self.board[3][col] = _piece(WHITE, PAWN)
            self.board[6][col] = _piece(BLACK, PAWN)

    # -------------------- 位板构建 --------------------

    def _bitboards(self) -> _Bitboards:
        """从二维列表一次性构建位板；O(90) 整数循环，整轮规则计算复用。"""
        side = {BLACK: 0, WHITE: 0}
        kind = {k: 0 for k in _ALL_KINDS}
        bit = 1
        for row in self.board:
            for cell in row:
                if cell:
                    side[cell // 10] |= bit
                    kind[cell % 10] |= bit
                bit <<= 1
        return _Bitboards(BitboardGeometry(ROWS, COLS), side, kind)

    # -------------------- 基础接口 --------------------

    def in_bounds(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols

    def piece_side(self, cell: int) -> int:
        return piece_side(cell)

    def count_pieces(self) -> Tuple[int, int]:
        red = dark = 0
        for row in self.board:
            for cell in row:
                if piece_side(cell) == BLACK:
                    red += 1
                elif piece_side(cell) == WHITE:
                    dark += 1
        return red, dark

    def copy(self) -> "ChessBoard":
        new_board = ChessBoard(self.size)
        self._base_copy_state(new_board)
        new_board._last_own_move = dict(self._last_own_move)
        new_board._repeat_streak = dict(self._repeat_streak)
        return new_board

    # -------------------- 禁止连续重复走法 --------------------

    def in_check(self, side=None) -> bool:
        """当前行棋方（或指定方）是否正被将军，供界面做醒目提示。"""
        if side is None:
            side = self.current_player
        return self._in_check(side)

    def is_repeat_move(self, move, side=None) -> bool:
        """本次走法是否与同一方上一手相同，或互为逆向（原路走回）。"""
        if side is None:
            side = self.current_player
        prev = self._last_own_move.get(side)
        if prev is None:
            return False
        src, dst = move
        ps, pd = prev
        return (src, dst) == (ps, pd) or (src, dst) == (pd, ps)

    def repeat_status(self, side=None):
        """返回 (当前连续重复次数, 禁止阈值)，供界面提示。"""
        if side is None:
            side = self.current_player
        return self._repeat_streak.get(side, 0), REPEAT_LIMIT

    def repeat_block_reason(self, move, side=None) -> str:
        """该走法若因连续重复被禁，返回提示文案；否则返回空串。"""
        if side is None:
            side = self.current_player
        if (self._repeat_streak.get(side, 0) + 1 >= REPEAT_LIMIT
                and self.is_repeat_move(move, side)):
            return "禁止连续重复走法（长打须变着），请改走其它着法"
        return ""

    def _repeat_blocked(self, move, side) -> bool:
        return bool(self.repeat_block_reason(move, side))

    def _note_move(self, src: int, dst: int, side: int) -> None:
        """落子后累计该方连续重复次数（推演路径也调用，保持规则一致）。"""
        repeat = self.is_repeat_move((src, dst), side)
        self._repeat_streak[side] = (self._repeat_streak.get(side, 0) + 1
                                     if repeat else 1)
        self._last_own_move[side] = (src, dst)

    def _snapshot(self) -> tuple:
        return super()._snapshot() + (dict(self._last_own_move),
                                      dict(self._repeat_streak))

    def _restore(self, snap: tuple) -> None:
        super()._restore(snap)
        self._last_own_move = snap[7]
        self._repeat_streak = snap[8]

    # -------------------- 走法生成 --------------------

    @staticmethod
    def _in_palace(row: int, col: int, side: int) -> bool:
        if not (3 <= col <= 5):
            return False
        return 7 <= row <= 9 if side == BLACK else 0 <= row <= 2

    @staticmethod
    def _own_half(row: int, side: int) -> bool:
        return row >= 5 if side == BLACK else row <= 4

    def _king_square(self, side: int, bb: Optional[_Bitboards] = None):
        """将位定位：位板 bit_length 一次得到，替代原先 90 格全扫描。"""
        if bb is None:
            bb = self._bitboards()
        mask = bb.kind[KING] & bb.side[side]
        if not mask:
            return None
        return divmod(mask.bit_length() - 1, COLS)

    def _facing_kings(self, bb: Optional[_Bitboards] = None) -> bool:
        """将帅同列且中间无子：视为非法局面（白脸将）。"""
        if bb is None:
            bb = self._bitboards()
        red = bb.kind[KING] & bb.side[BLACK]
        dark = bb.kind[KING] & bb.side[WHITE]
        # 与旧实现保持一致：任一方将缺失 / 不同列时均不算照面
        if not red or not dark:
            return False
        ri, di = red.bit_length() - 1, dark.bit_length() - 1
        rr, rc = divmod(ri, COLS)
        dr, dc = divmod(di, COLS)
        if rc != dc:
            return False
        step = 1 if dr > rr else -1
        for i in bb.geo.ray(ri, step, 0):
            if (bb.occ >> i) & 1:
                return i == di
        return False

    def _slide(self, row: int, col: int, side: int,
               cannon: bool, bb: Optional[_Bitboards] = None) -> List[int]:
        """车 / 炮的直线目标；cannon=True 时吃子必须隔恰好一个炮架。"""
        if bb is None:
            bb = self._bitboards()
        geo, occ, own = bb.geo, bb.occ, bb.side[side]
        idx = row * COLS + col
        result: List[int] = []
        for dr, dc in _ORTHO:
            jumped = False
            for i in geo.ray(idx, dr, dc):
                bit = 1 << i
                occupied = bool(occ & bit)
                if cannon:
                    if not jumped:
                        if not occupied:
                            result.append(i)
                        else:
                            jumped = True
                    elif occupied:
                        if not (own & bit):
                            result.append(i)
                        break
                else:
                    if not occupied:
                        result.append(i)
                    else:
                        if not (own & bit):
                            result.append(i)
                        break
        return result

    def _pseudo_targets(self, row: int, col: int, cell: int,
                        bb: Optional[_Bitboards] = None) -> List[int]:
        """单枚棋子的伪合法目标（不含将军过滤）。"""
        if bb is None:
            bb = self._bitboards()
        occ, own = bb.occ, bb.side[piece_side(cell)]
        side, kind = piece_side(cell), piece_kind(cell)
        targets: List[int] = []

        def add(r: int, c: int) -> None:
            if 0 <= r < ROWS and 0 <= c < COLS:
                idx = r * COLS + c
                if not (own & (1 << idx)):
                    targets.append(idx)

        if kind == KING:
            for dr, dc in _ORTHO:
                r, c = row + dr, col + dc
                if self._in_palace(r, c, side):
                    add(r, c)
        elif kind == ADVISOR:
            for dr, dc in _DIAG:
                r, c = row + dr, col + dc
                if self._in_palace(r, c, side):
                    add(r, c)
        elif kind == ELEPHANT:
            for dr, dc in _ELEPHANT_STEPS:
                r, c = row + dr, col + dc
                if not (0 <= r < ROWS and 0 <= c < COLS):
                    continue
                if not self._own_half(r, side):
                    continue
                er, ec = row + dr // 2, col + dc // 2
                if not (0 <= er < ROWS and 0 <= ec < COLS):
                    continue
                if not (occ & (1 << (er * COLS + ec))):
                    add(r, c)
        elif kind == HORSE:
            for dr, dc in _HORSE_STEPS:
                r, c = row + dr, col + dc
                if not (0 <= r < ROWS and 0 <= c < COLS):
                    continue
                lr = row + (dr // 2 if abs(dr) == 2 else 0)
                lc = col + (dc // 2 if abs(dc) == 2 else 0)
                if not (0 <= lr < ROWS and 0 <= lc < COLS):
                    continue
                if occ & (1 << (lr * COLS + lc)):
                    continue
                add(r, c)
        elif kind in (ROOK, CANNON):
            targets.extend(self._slide(row, col, side, kind == CANNON, bb))
        elif kind == PAWN:
            forward = -1 if side == BLACK else 1
            add(row + forward, col)
            crossed = row <= 4 if side == BLACK else row >= 5
            if crossed:
                add(row, col - 1)
                add(row, col + 1)
        return targets

    def _pseudo_moves(self, side: int,
                      bb: Optional[_Bitboards] = None) -> List[Tuple[int, int]]:
        """只遍历该方棋子所在的位，不再逐格扫过整张 10×9 棋盘。"""
        if bb is None:
            bb = self._bitboards()
        result: List[Tuple[int, int]] = []
        for src in iter_bits(bb.side[side]):
            r, c = divmod(src, COLS)
            cell = self.board[r][c]
            for dst in self._pseudo_targets(r, c, cell, bb):
                result.append((src, dst))
        return result

    def _in_check(self, side: int, bb: Optional[_Bitboards] = None) -> bool:
        """
        将位反向探测将军 —— 与「枚举对手全部伪合法步」完全等价，但只需
        检查将位周围 4 条射线 + 8 个马来源位 + 3 个兵来源位。

        威胁将位的兵种只有车、炮、马、兵（士 / 象受九宫与河界限制，
        不可能走到对方将位；将帅照面由 _facing_kings 单独处理）。
        """
        if bb is None:
            bb = self._bitboards()
        king_mask = bb.kind[KING] & bb.side[side]
        if not king_mask:
            return True                # 将已被吃掉
        ki = king_mask.bit_length() - 1
        kr, kc = divmod(ki, COLS)
        opp = self.opponent(side)
        enemy = bb.side[opp]
        rooks = bb.kind[ROOK] & enemy
        cannons = bb.kind[CANNON] & enemy
        horses = bb.kind[HORSE] & enemy
        pawns = bb.kind[PAWN] & enemy
        occ, geo = bb.occ, bb.geo

        # 1) 车：射线上第一个挡子即敌车；炮：第二个挡子是敌炮（第一个当炮架）
        for dr, dc in _ORTHO:
            first = second = -1
            for i in geo.ray(ki, dr, dc):
                if (occ >> i) & 1:
                    if first < 0:
                        first = i
                    else:
                        second = i
                        break
            if first < 0:
                continue
            if (rooks >> first) & 1:
                return True
            if second >= 0 and (cannons >> second) & 1:
                return True

        # 2) 马：反查 8 个「能跳到将位」的来源格，并校验马腿是否为空
        for dr, dc in _HORSE_STEPS:
            mr, mc = kr - dr, kc - dc
            if not (0 <= mr < ROWS and 0 <= mc < COLS):
                continue
            if not (horses >> (mr * COLS + mc)) & 1:
                continue
            lr = mr + (dr // 2 if abs(dr) == 2 else 0)
            lc = mc + (dc // 2 if abs(dc) == 2 else 0)
            if not (occ >> (lr * COLS + lc)) & 1:
                return True

        # 3) 兵 / 卒：正前方一格，或过河后左右横吃
        fwd = -1 if opp == BLACK else 1
        pr, pc = kr - fwd, kc
        if (0 <= pr < ROWS and 0 <= pc < COLS
                and (pawns >> (pr * COLS + pc)) & 1):
            return True
        for dc in (-1, 1):
            pr, pc = kr, kc + dc
            if not (0 <= pr < ROWS and 0 <= pc < COLS):
                continue
            if not (pawns >> (pr * COLS + pc)) & 1:
                continue
            if not self._own_half(pr, opp):
                return True
        return False

    def _try_move(self, src: int, dst: int):
        """原地试走，返回恢复函数；不修改 history / 回合等状态。"""
        fr, fc = decode_sq(src)
        tr, tc = decode_sq(dst)
        saved = self.board[tr][tc]
        moving = self.board[fr][fc]
        self.board[fr][fc] = EMPTY
        self.board[tr][tc] = moving

        def restore() -> None:
            self.board[fr][fc] = moving
            self.board[tr][tc] = saved

        return restore

    def _try_move_bb(self, src: int, dst: int, bb: _Bitboards):
        """
        试走并同步更新位板，使整轮合法步生成只需构建一次位板。
        restore() 同时还原二维列表与位板。
        """
        fr, fc = decode_sq(src)
        tr, tc = decode_sq(dst)
        saved = self.board[tr][tc]
        moving = self.board[fr][fc]
        self.board[fr][fc] = EMPTY
        self.board[tr][tc] = moving

        sb, tb = 1 << src, 1 << dst
        ms, mk = moving // 10, moving % 10
        bb.side[ms] = (bb.side[ms] & ~sb) | tb
        bb.kind[mk] = (bb.kind[mk] & ~sb) | tb
        if saved:
            ss, sk = saved // 10, saved % 10
            bb.side[ss] &= ~tb
            bb.kind[sk] &= ~tb
        bb.occ = bb.side[BLACK] | bb.side[WHITE]

        def restore() -> None:
            self.board[fr][fc] = moving
            self.board[tr][tc] = saved
            bb.side[ms] = (bb.side[ms] & ~tb) | sb
            bb.kind[mk] = (bb.kind[mk] & ~tb) | sb
            if saved:
                bb.side[ss] |= tb
                bb.kind[sk] |= tb
            bb.occ = bb.side[BLACK] | bb.side[WHITE]

        return restore

    def _is_legal_move(self, src: int, dst: int, side: int,
                       bb: Optional[_Bitboards] = None) -> bool:
        if bb is None:
            bb = self._bitboards()
        fr, fc = decode_sq(src)
        if piece_side(self.board[fr][fc]) != side:
            return False
        if dst not in self._pseudo_targets(fr, fc, self.board[fr][fc], bb):
            return False
        restore = self._try_move_bb(src, dst, bb)
        try:
            ok = not self._in_check(side, bb) and not self._facing_kings(bb)
        finally:
            restore()
        return ok

    def _cache_key(self) -> tuple:
        """
        缓存键：命中路径用 C 层面的嵌套 tuple 构造（比重建位板更便宜），
        未命中时才由 get_legal_moves 构建位板做规则计算。
        连续重复状态会影响合法步集合，必须一并进键，避免不同历史误命中。
        """
        side = self.current_player
        return (side, tuple(tuple(row) for row in self.board),
                self._repeat_streak.get(side, 0),
                self._last_own_move.get(side))

    def get_legal_moves(self) -> List[Tuple[int, int]]:
        key = self._cache_key()
        cached = self._legal_cache.get(key)
        if cached is not None:
            return list(cached)
        bb = self._bitboards()
        side = self.current_player
        moves = [(src, dst) for src, dst in self._pseudo_moves(side, bb)
                 if self._is_legal_move(src, dst, side, bb)
                 and not self._repeat_blocked((src, dst), side)]
        if len(self._legal_cache) > 2048:
            self._legal_cache.clear()
        self._legal_cache[key] = tuple(moves)
        return moves

    def _has_legal_move(self) -> bool:
        """
        终局判定专用：只要找到第一步合法走法就返回，不必算完整列表。
        搜索中绝大多数局面都有合法步，这能把落子后的终局检查降一个量级；
        被「禁止连续重复走法」挡掉的步同样不算数。
        """
        key = self._cache_key()
        cached = self._legal_cache.get(key)
        if cached is not None:
            return bool(cached)
        bb = self._bitboards()
        side = self.current_player
        for src, dst in self._pseudo_moves(side, bb):
            if (self._is_legal_move(src, dst, side, bb)
                    and not self._repeat_blocked((src, dst), side)):
                return True
        return False

    # -------------------- 落子与终局 --------------------

    def _apply_core(self, src: int, dst: int) -> None:
        """落子 + 状态更新 + 终局判定（不含合法性校验）。"""
        fr, fc = decode_sq(src)
        tr, tc = decode_sq(dst)
        side = self.current_player
        self.board[tr][tc] = self.board[fr][fc]
        self.board[fr][fc] = EMPTY
        self.last_move = (src, dst)
        self.move_count += 1
        self._note_move(src, dst, side)
        self._record_move(tr, tc, side)
        self._swap_player()
        self._check_game_end()

    def _apply_unchecked(self, move) -> bool:
        """push() 用：调用方保证 move 合法，跳过重复校验但保留终局判定。"""
        if self.game_over:
            return False
        src, dst = move
        if self._repeat_blocked(move, self.current_player):
            return False
        self._apply_core(src, dst)
        return True

    def apply_move(self, move: Tuple[int, int]) -> bool:
        if self.game_over or not isinstance(move, tuple) or len(move) != 2:
            return False
        src, dst = move
        if not isinstance(src, int) or not isinstance(dst, int):
            return False
        if not (0 <= src < ROWS * COLS and 0 <= dst < ROWS * COLS):
            return False
        if self._repeat_blocked(move, self.current_player):
            return False
        if not self._is_legal_move(src, dst, self.current_player):
            return False
        self._apply_core(src, dst)
        return True

    def fast_apply(self, move: Tuple[int, int]) -> bool:
        """
        搜索内部快速落子：调用方已保证 move 合法，跳过将军复检与终局判定。

        AI 推演（MCTS rollout / 进化算法解码）每步只需移动棋子和切换回合，
        重复做完整的将军过滤会把 10 秒预算全耗在规则层。
        """
        src, dst = move
        fr, fc = decode_sq(src)
        tr, tc = decode_sq(dst)
        side = self.current_player
        self.board[tr][tc] = self.board[fr][fc]
        self.board[fr][fc] = EMPTY
        self.last_move = move
        self.move_count += 1
        self._note_move(src, dst, side)
        self._swap_player()
        return True

    def _check_game_end(self) -> None:
        """对方无合法步（将死或困毙）即终局，胜方为刚落子的一方。"""
        if self._has_legal_move():
            return
        self.game_over = True
        self.winner = self.opponent(self.current_player)

    # -------------------- 供 UI / 评估使用 --------------------

    def move_from_clicks(self, first, second):
        """把两次点击 (row, col) 转成棋盘走法；不合法返回 None。"""
        if first is None or second is None:
            return None
        move = (encode_sq(*first), encode_sq(*second))
        return move if self._is_legal_move(*move, self.current_player) else None

    def last_player(self) -> int:
        """返回刚落子一方的阵营，供棋谱记录（编码棋子不是 1/2）。"""
        if self.last_move is None:
            return EMPTY
        tr, tc = decode_sq(self.last_move[1])
        return piece_side(self.board[tr][tc])

    def piece_name_at(self, row: int, col: int) -> str:
        return piece_name(self.board[row][col]) if self.in_bounds(row, col) else ""

    def piece_values(self, side: int) -> int:
        """简易子力总分，供评估函数使用。"""
        values = {KING: 10000, ROOK: 900, CANNON: 450, HORSE: 400,
                  ELEPHANT: 200, ADVISOR: 200, PAWN: 100}
        total = 0
        for row in self.board:
            for cell in row:
                if piece_side(cell) == side:
                    total += values.get(piece_kind(cell), 0)
        return total
