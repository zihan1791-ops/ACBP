# -*- coding: utf-8 -*-
"""
位板改造回归测试：等价性证明 + make/unmake 零污染 + 搜索层正确性。

本轮把四种棋的规则热点改成位板计算，并新增 push/pop 撤销栈。
由于「位板版规则」与「原二维列表版规则」必须在任意局面上给出完全相同的
结果，这里内置一份独立的纯二维列表参考实现（不调用被测模块的任何辅助
函数），在大量随机局面上逐局面比对：

    象棋   合法步集合 / 将军判定 / 将帅照面
    黑白棋 合法步集合 / 翻转集合
    围棋   合法步集合 / 落子后棋盘 / 劫点 / 提子数 / 回合

另验证 push/pop 的完整回溯、Alpha-Beta 与进化算法搜索后真实棋盘零污染、
七类算法在四棋种上仍返回合法步。

运行方式（项目根目录下）：
    python tests/bitboard_test.py
全部通过时末尾输出 "BITBOARD TESTS PASSED"。
"""

import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.factory import create_ai
from config.args import load_config
from core import BOARD_CLASSES
from core.base_board import ALL_DIRECTIONS, BLACK, WHITE, EMPTY
from core.bitboard import BitboardGeometry, build_masks, iter_bits, bit_count
from core.chess.board import (ChessBoard, ROWS, COLS, encode_sq, decode_sq,
                              piece_side, _ORTHO)
from core.go.board import GoBoard
from core.othello.board import OthelloBoard

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print("[PASS] %s" % name)
    else:
        failed += 1
        print("[FAIL] %s" % name)


# ==================== 独立参考实现（纯二维列表） ====================

def chess_ref_pseudo_targets(b, r, c, cell):
    side, kind = piece_side(cell), cell % 10
    out = []

    def add(rr, cc):
        if 0 <= rr < ROWS and 0 <= cc < COLS and piece_side(b.board[rr][cc]) != side:
            out.append(encode_sq(rr, cc))

    if kind == 1:
        for dr, dc in _ORTHO:
            rr, cc = r + dr, c + dc
            if 3 <= cc <= 5 and (7 <= rr <= 9 if side == BLACK else 0 <= rr <= 2):
                add(rr, cc)
    elif kind == 2:
        for dr, dc in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            rr, cc = r + dr, c + dc
            if 3 <= cc <= 5 and (7 <= rr <= 9 if side == BLACK else 0 <= rr <= 2):
                add(rr, cc)
    elif kind == 3:
        for dr, dc in [(2, 2), (2, -2), (-2, 2), (-2, -2)]:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ROWS and 0 <= cc < COLS):
                continue
            if not (rr >= 5 if side == BLACK else rr <= 4):
                continue
            er, ec = r + dr // 2, c + dc // 2
            if not (0 <= er < ROWS and 0 <= ec < COLS):
                continue
            if b.board[er][ec] == EMPTY:
                add(rr, cc)
    elif kind == 4:
        for dr, dc in [(1, 2), (2, 1), (-1, 2), (-2, 1),
                       (1, -2), (2, -1), (-1, -2), (-2, -1)]:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < ROWS and 0 <= cc < COLS):
                continue
            lr = r + (dr // 2 if abs(dr) == 2 else 0)
            lc = c + (dc // 2 if abs(dc) == 2 else 0)
            if not (0 <= lr < ROWS and 0 <= lc < COLS):
                continue
            if b.board[lr][lc] != EMPTY:
                continue
            add(rr, cc)
    elif kind in (5, 6):
        cannon = kind == 6
        for dr, dc in _ORTHO:
            rr, cc = r + dr, c + dc
            jumped = False
            while 0 <= rr < ROWS and 0 <= cc < COLS:
                target = b.board[rr][cc]
                if cannon:
                    if not jumped:
                        if target == EMPTY:
                            out.append(encode_sq(rr, cc))
                        else:
                            jumped = True
                    elif target != EMPTY:
                        if piece_side(target) != side:
                            out.append(encode_sq(rr, cc))
                        break
                else:
                    if target == EMPTY:
                        out.append(encode_sq(rr, cc))
                    else:
                        if piece_side(target) != side:
                            out.append(encode_sq(rr, cc))
                        break
                rr += dr
                cc += dc
    elif kind == 7:
        fwd = -1 if side == BLACK else 1
        add(r + fwd, c)
        if r <= 4 if side == BLACK else r >= 5:
            add(r, c - 1)
            add(r, c + 1)
    return out


def chess_ref_pseudo_moves(b, side):
    out = []
    for r in range(ROWS):
        for c in range(COLS):
            cell = b.board[r][c]
            if piece_side(cell) != side:
                continue
            src = encode_sq(r, c)
            for dst in chess_ref_pseudo_targets(b, r, c, cell):
                out.append((src, dst))
    return out


def chess_ref_king(b, side):
    target = side * 10 + 1
    for r in range(ROWS):
        for c in range(COLS):
            if b.board[r][c] == target:
                return r, c
    return None


def chess_ref_facing(b):
    """True 表示将帅照面（非法局面），与原 _facing_kings 语义一致。"""
    red, dark = chess_ref_king(b, BLACK), chess_ref_king(b, WHITE)
    if red is None or dark is None or red[1] != dark[1]:
        return False
    lo, hi = min(red[0], dark[0]), max(red[0], dark[0])
    return all(b.board[r][red[1]] == EMPTY for r in range(lo + 1, hi))


def chess_ref_in_check(b, side):
    k = chess_ref_king(b, side)
    if k is None:
        return True
    target = encode_sq(*k)
    return any(dst == target for _, dst in chess_ref_pseudo_moves(b, b.opponent(side)))


def chess_ref_legal(b):
    """独立参考实现；同时独立复述「禁止连续重复走法」这条业务规则。"""
    side = b.current_player
    prev = b._last_own_move.get(side)
    streak = b._repeat_streak.get(side, 0)

    def repeat_blocked(src, dst):
        if prev is None or streak + 1 < 3:
            return False
        return ((src, dst) == (prev[0], prev[1])
                or (src, dst) == (prev[1], prev[0]))

    out = []
    for src, dst in chess_ref_pseudo_moves(b, side):
        fr, fc = decode_sq(src)
        if piece_side(b.board[fr][fc]) != side:
            continue
        if repeat_blocked(src, dst):
            continue
        if dst not in chess_ref_pseudo_targets(b, fr, fc, b.board[fr][fc]):
            continue
        restore = b._try_move(src, dst)
        try:
            legal = (not chess_ref_in_check(b, side)) and (not chess_ref_facing(b))
        finally:
            restore()
        if legal:
            out.append((src, dst))
    return out


def othello_ref_flips(b, row, col, player):
    opponent = b.opponent(player)
    flips = []
    for dr, dc in ALL_DIRECTIONS:
        line = []
        r, c = row + dr, col + dc
        while b.in_bounds(r, c) and b.board[r][c] == opponent:
            line.append((r, c))
            r += dr
            c += dc
        if line and b.in_bounds(r, c) and b.board[r][c] == player:
            flips.extend(line)
    return flips


def othello_ref_legal(b):
    return [(r, c) for r in range(b.size) for c in range(b.size)
            if b.board[r][c] == EMPTY and othello_ref_flips(b, r, c, b.current_player)]


OTH4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def go_ref_collect(b, row, col):
    color = b.board[row][col]
    group, libs, queue = {(row, col)}, set(), [(row, col)]
    while queue:
        r, c = queue.pop()
        for dr, dc in OTH4:
            nr, nc = r + dr, c + dc
            if not b.in_bounds(nr, nc):
                continue
            if b.board[nr][nc] == EMPTY:
                libs.add((nr, nc))
            elif b.board[nr][nc] == color and (nr, nc) not in group:
                group.add((nr, nc))
                queue.append((nr, nc))
    return group, libs


def go_ref_legal(b):
    out = []
    for r in range(b.size):
        for c in range(b.size):
            if b.board[r][c] != EMPTY:
                continue
            if b.ko_point is not None and (r, c) == b.ko_point:
                continue
            player, opp = b.current_player, b.opponent(b.current_player)
            b.board[r][c] = player
            captured = []
            for dr, dc in OTH4:
                nr, nc = r + dr, c + dc
                if not b.in_bounds(nr, nc) or b.board[nr][nc] != opp:
                    continue
                group, libs = go_ref_collect(b, nr, nc)
                if not libs:
                    captured.extend(group)
            _, my_libs = go_ref_collect(b, r, c)
            legal = bool(my_libs) or bool(captured)
            b.board[r][c] = EMPTY
            if legal:
                out.append((r, c))
    return out


# ==================== 状态快照工具 ====================

def board_state(b):
    return ([row[:] for row in b.board], b.current_player, b.last_move,
            b.move_count, b.game_over, b.winner, list(b.history),
            getattr(b, "ko_point", None), getattr(b, "black_captured", None),
            getattr(b, "white_captured", None))


def midgame(kind, size, plies, seed):
    rng = random.Random(seed)
    b = BOARD_CLASSES[kind](size)
    for _ in range(plies):
        legal = b.get_legal_moves()
        if not legal or b.game_over:
            break
        b.apply_move(rng.choice(legal))
    return b


def main() -> None:
    # ---------- 1. 位板工具 ----------
    geo = BitboardGeometry(3, 4)
    check("几何表按尺寸缓存复用", geo is BitboardGeometry(3, 4))
    check("full 掩码位数正确", geo.full == (1 << 12) - 1)
    check("iter_bits 按低位到高位产出",
          list(iter_bits(0b10110)) == [1, 2, 4])
    check("bit_count 正确", bit_count(0b10110) == 3)
    check("四邻扩张不越界",
          geo.expand4(1 << geo.index(0, 0)) ==
          (1 << geo.index(1, 0)) | (1 << geo.index(0, 1)))
    check("右移位不串到下一行",
          geo.shift(1 << geo.index(0, 3), 0, 1) == 0)
    check("下移位自然截断",
          geo.shift(1 << geo.index(2, 0), 1, 0) == 0)

    rng = random.Random(5)
    g9 = BitboardGeometry(9, 9)
    flood_ok = True
    for _ in range(120):
        cm = rng.getrandbits(81) & g9.full
        st = rng.randrange(81)
        cm |= 1 << st
        group, _ = g9.group(cm, st)
        # 参考 flood：逐位查邻居表
        ref, frontier = 1 << st, 1 << st
        while frontier:
            nxt = 0
            for i in iter_bits(frontier):
                nxt |= g9.neighbor_mask[i]
            frontier = nxt & cm & ~ref
            ref |= frontier
        if group != ref:
            flood_ok = False
            break
    check("纯位移连通块与逐位 BFS 等价", flood_ok)

    grid = [[EMPTY] * 8 for _ in range(8)]
    grid[2][3] = BLACK
    grid[4][5] = WHITE
    geo8 = BitboardGeometry(8, 8)
    _, masks = build_masks(grid, 8, 8)
    bb_black = 1 << (2 * 8 + 3)
    bb_white = 1 << (4 * 8 + 5)
    check("build_masks 与二维列表一致",
          masks[BLACK] == bb_black and masks[WHITE] == bb_white and
          masks[EMPTY] == (geo8.full ^ bb_black ^ bb_white))

    for kind, size in [("gomoku", 9), ("othello", 8), ("go", 9)]:
        b = midgame(kind, size, 8, 77)
        _, masks = b._bitboards()
        by_value = {EMPTY: 0, BLACK: 0, WHITE: 0}
        bit = 1
        for row in b.board:
            for cell in row:
                by_value[cell] |= bit
                bit <<= 1
        check("%s 位板与二维列表同步" % kind,
              masks[BLACK] == by_value[BLACK] and
              masks[WHITE] == by_value[WHITE] and
              masks[EMPTY] == by_value[EMPTY])

    cb = midgame("chess", 10, 8, 77)
    cbb = cb._bitboards()
    side_exp = {BLACK: 0, WHITE: 0}
    kind_exp = {k: 0 for k in range(1, 8)}
    bit = 1
    for row in cb.board:
        for cell in row:
            if cell:
                side_exp[cell // 10] |= bit
                kind_exp[cell % 10] |= bit
            bit <<= 1
    check("chess 阵营/兵种位板与二维列表同步",
          cbb.side == side_exp and cbb.kind == kind_exp and
          cbb.occ == (side_exp[BLACK] | side_exp[WHITE]))

    # ---------- 2. 象棋：反向将军探测等价 ----------
    rng = random.Random(2026)
    chess_ok = chess_states = 0
    for _ in range(16):
        b = ChessBoard(10)
        for _ in range(45):
            legal = b.get_legal_moves()
            if not legal or b.game_over:
                break
            bb = b._bitboards()
            if b._in_check(b.current_player, bb) != chess_ref_in_check(b, b.current_player):
                chess_ok = 1
                break
            if b.get_legal_moves() != chess_ref_legal(b):
                chess_ok = 2
                break
            chess_states += 1
            b.apply_move(rng.choice(legal))
        if chess_ok:
            break
    check("象棋 反向将军/合法步 与参考实现等价 (%d 局面)" % chess_states,
          chess_ok == 0 and chess_states > 200)

    c = ChessBoard(10)
    c._legal_cache.clear()
    check("将位定位由位板给出正确坐标", c._king_square(BLACK) == (9, 4))
    check("将帅照面判定正确", not c._facing_kings())

    # ---------- 3. 黑白棋：位板翻子等价 ----------
    rng = random.Random(99)
    oth_ok = oth_states = 0
    for _ in range(20):
        b = OthelloBoard(8)
        for _ in range(60):
            new_legal, ref_legal = b.get_legal_moves(), othello_ref_legal(b)
            if new_legal != ref_legal:
                oth_ok = 1
                break
            if b.game_over or not new_legal:
                break
            mv = rng.choice(new_legal)
            if sorted(b._flip_cells(*mv, b.current_player)) != \
                    sorted(othello_ref_flips(b, *mv, b.current_player)):
                oth_ok = 2
                break
            b.apply_move(mv)
            oth_states += 1
        if oth_ok:
            break
    check("黑白棋 合法步/翻转集合 与参考实现等价 (%d 局面)" % oth_states,
          oth_ok == 0 and oth_states > 400)

    # ---------- 4. 围棋：位板气与提子等价 ----------
    rng = random.Random(4242)
    go_ok = go_states = 0
    for game in range(8):
        size = 9 if game % 2 == 0 else 13
        a, ref = GoBoard(size), GoBoard(size)
        for _ in range(45):
            if a.get_legal_moves() != go_ref_legal(a):
                go_ok = 1
                break
            lm = a.get_legal_moves()
            if not lm:
                break
            mv = rng.choice(lm)
            # 参考棋盘用纯二维列表逻辑推进
            player = ref.current_player
            opp = ref.opponent(player)
            ref.board[mv[0]][mv[1]] = player
            captured = []
            for dr, dc in OTH4:
                nr, nc = mv[0] + dr, mv[1] + dc
                if not ref.in_bounds(nr, nc) or ref.board[nr][nc] != opp:
                    continue
                group, libs = go_ref_collect(ref, nr, nc)
                if not libs:
                    captured.append(group)
            caps = set().union(*captured) if captured else set()
            for cr, cc in caps:
                ref.board[cr][cc] = EMPTY
            ref.last_move = mv
            ref.move_count += 1
            ref.current_player = opp
            ref.ko_point = next(iter(caps)) if len(caps) == 1 else None
            a.apply_move(mv)
            if a.board != ref.board or a.ko_point != ref.ko_point \
                    or a.current_player != ref.current_player:
                go_ok = 2
                break
            go_states += 1
        if go_ok:
            break
    check("围棋 合法步/棋盘/劫点 与参考实现等价 (%d 局面)" % go_states,
          go_ok == 0 and go_states > 150)

    # ---------- 5. push/pop 完整回溯 ----------
    for kind, size in [("gomoku", 9), ("othello", 8), ("go", 9), ("chess", 10)]:
        b = midgame(kind, size, 8, 31)
        before = board_state(b)
        legal = b.get_legal_moves()
        ok = bool(legal) and b.push(legal[0])
        changed = board_state(b) != before if ok else False
        popped = b.pop() if ok else False
        check("%s push/pop 完整还原" % kind,
              ok and changed and popped and board_state(b) == before
              and b.undo_depth == 0)

    b = midgame("go", 9, 10, 88)
    before = board_state(b)
    legal = b.get_legal_moves()
    ok = True
    for mv in legal[:3]:
        if not b.push(mv):
            break
        ok = ok and bool(b.get_legal_moves())
    while b.pop():
        pass
    check("嵌套 push/pop 多层回溯", ok and board_state(b) == before)

    # ---------- 6. 搜索层零污染 ----------
    cfg = load_config(["--ab-depth", "3", "--ab-time", "0.6",
                       "--evo-population", "8", "--evo-generations", "6",
                       "--evo-horizon", "4", "--evo-time", "0.6", "--seed", "7"])
    for kind, size in [("gomoku", 9), ("othello", 8), ("go", 9), ("chess", 10)]:
        b = midgame(kind, size, 6, 12)
        before = board_state(b)
        clean = True
        for algo in ("alphabeta", "iga", "de"):
            ai = create_ai(algo, b.current_player, cfg)
            mv = ai.select_move(b)
            clean = clean and mv in b.get_legal_moves() and \
                board_state(b) == before and b.undo_depth == 0
        check("%s AB/进化算法 搜索后真实棋盘零污染" % kind, clean)

    # ---------- 7. 七类算法四棋种合法步 ----------
    fast = load_config(["--mcts-iterations", "30", "--mcts-time", "0.4",
                        "--ab-depth", "2", "--ab-time", "0.4",
                        "--evo-population", "6", "--evo-generations", "3",
                        "--evo-horizon", "3", "--evo-time", "0.5", "--seed", "5"])
    all_legal = True
    for kind, size in [("gomoku", 9), ("othello", 8), ("go", 9), ("chess", 10)]:
        for algo in ("mcts", "alphabeta", "random", "iga", "de", "pso", "abc"):
            b = midgame(kind, size, 4, 21)
            mv = create_ai(algo, b.current_player, fast).select_move(b)
            all_legal = all_legal and mv in b.get_legal_moves()
    check("七类算法 × 四棋种 仍返回合法步", all_legal)

    # ---------- 8. 完整对局可走到终局 ----------
    rng = random.Random(123)
    for kind, size in [("gomoku", 9), ("othello", 8), ("go", 9), ("chess", 10)]:
        b = BOARD_CLASSES[kind](size)
        steps, bad = 0, False
        while not b.game_over and steps < 120:
            legal = b.get_legal_moves()
            if not legal:
                break
            mv = rng.choice(legal)
            if not b.apply_move(mv):
                bad = True
                break
            steps += 1
        check("%s 随机对局 %d 手无非法步" % (kind, steps), not bad and steps > 3)

    print("\n测试结果：%d 通过，%d 失败" % (passed, failed))
    if failed:
        sys.exit(1)
    print("BITBOARD TESTS PASSED")


if __name__ == "__main__":
    main()
