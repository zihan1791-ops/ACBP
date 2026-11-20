"""Local, indexed search recordings shared by the AI and the desktop viewer."""

import json
import os
import sqlite3
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

from core import BOARD_CLASSES
from utils.logger import log_warn


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Recording:
    def __init__(self, folder, ai, board):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        game = next(k for k, cls in BOARD_CLASSES.items() if isinstance(board, cls))
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        side = "黑" if ai.player == 1 else "白"
        self.path = folder / f"{stamp}_{game}_{board.move_count+1:03}_{side}_{ai.name}_{uuid4().hex[:6]}.sqlite"
        self.db = sqlite3.connect(self.path)
        self.enabled = True
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("pragma synchronous=NORMAL")
        self.db.executescript("""
            create table meta(data text);
            create table events(step integer primary key, node integer, kind text, data text);
            create index by_kind on events(kind,step);
            create table nodes(id integer primary key, parent integer, move text, label text);
            create index by_parent on nodes(parent,id);
            create table stats(node integer, step integer, data text, primary key(node,step));
        """)
        info = dict(game=game, algo=ai.name, player=ai.player, cells=board.board,
                    size=board.size, ply=board.move_count, pid=os.getpid())
        for key in ("ko_point", "black_captured", "white_captured", "_last_own_move", "_repeat_streak"):
            if hasattr(board, key):
                info[key] = getattr(board, key)
        self.db.execute("insert into meta values (?)", (dumps(info),))
        self.step = 0
        self.iteration = 0
        self.last_commit = time.monotonic()
        self.rollouts = (folder / "rollouts.enabled").exists()
        self.root = self.add(0, None, "根局面")
        self.db.commit()

    def write(self, sql, args=()):
        if self.enabled:
            try:
                self.db.execute(sql, args)
            except sqlite3.Error as exc:
                self.enabled = False
                log_warn(f"搜索记录写入中断：{exc}")

    def commit(self):
        if self.db.in_transaction:
            self.write("commit")

    def event(self, node, kind, data=None):
        self.step += 1
        # Commit previous complete events before starting the next one.
        if self.step % 512 == 0 or time.monotonic() - self.last_commit >= .12:
            self.commit()
            self.last_commit = time.monotonic()
        self.write("insert into events values (?,?,?,?)", (self.step, node, kind, dumps(data or {})))

    def add(self, parent, move, label, **state):
        node = self.step + 1
        self.event(node, label)
        self.write("insert into nodes values (?,?,?,?)", (node, parent, dumps(move), label))
        if state:
            self.stat(node, state)
        return node

    def stat(self, node, state):
        self.write("insert into stats values (?,?,?)", (node, self.step, dumps(state)))

    def simulation(self, leaf, outcome, moves):
        self.iteration += 1
        self.event(leaf.record_id, "模拟回传", dict(iteration=self.iteration, outcome=outcome, rollout=moves))
        while leaf is not None:
            self.stat(leaf.record_id, dict(visits=leaf.visits, wins=leaf.wins))
            leaf = leaf.parent

    def returned(self, node, score, alpha, beta, bound):
        self.event(node, "返回")
        self.stat(node, dict(score=score, alpha=alpha, beta=beta, bound=bound))


def record_search(select_move):
    @wraps(select_move)
    def run(ai, board, on_progress=None):
        folder = getattr(ai, "analysis_dir", None) or getattr(ai.config, "analysis_dir", None)
        ai.record = None
        if folder:
            try:
                ai.record = Recording(folder, ai, board)
            except (OSError, sqlite3.Error) as exc:
                log_warn(f"无法创建搜索记录：{exc}")
        try:
            move = select_move(ai, board, on_progress)
            if ai.record:
                ai.record.event(ai.record.root, "完成", dict(move=move, note=ai.think.note))
                ai.record.commit()
            return move
        finally:
            if ai.record:
                ai.record.db.close()
                ai.record = None
    return run
