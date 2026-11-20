"""ACBP 搜索分析器。运行 python analyzer.py，或从对局右侧打开。"""

import json
import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import BOARD_CLASSES
from core.chess.board import decode_sq, piece_name, piece_side
from utils.paths import resolve_path


def open_record(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.15)
    try:
        info = json.loads(db.execute("select data from meta").fetchone()[0])
        return db, info
    except Exception:
        db.close()
        raise


def position(info, moves):
    board = BOARD_CLASSES[info["game"]](info["size"])
    board.board = [row[:] for row in info["cells"]]
    board.current_player = info["player"]
    board.move_count = info["ply"]
    for key in ("black_captured", "white_captured", "ko_point"):
        if info.get(key) is not None:
            setattr(board, key, tuple(info[key]) if key == "ko_point" else info[key])
    if info["game"] == "chess":
        board._last_own_move = {int(k): tuple(v) if v else None
                                for k, v in info["_last_own_move"].items()}
        board._repeat_streak = {int(k): v for k, v in info["_repeat_streak"].items()}
    for move in moves:
        if not board.apply_move(tuple(move)):
            raise ValueError(f"无法还原走法 {move}")
    return board.board


class Analyzer:
    def __init__(self, window, folder=None):
        self.window = window
        self.folder = folder
        self.db = self.path = None
        self.paths = []
        self.latest = self.cursor = 0
        self.auto_opened = set()
        self.game_process = None
        self.after_id = None
        self.follow = tk.BooleanVar(value=True)
        self.rollouts = tk.BooleanVar(value=bool(folder and (folder / "rollouts.enabled").exists()))
        self.summary = tk.StringVar(value="启动对局或打开一组已有的搜索记录。")
        self.details = tk.StringVar()
        self.index = tk.StringVar(value="0")
        self.slider = tk.DoubleVar(value=1)
        window.title("ACBP 搜索分析器")
        window.geometry("1090x705")
        window.minsize(800, 550)
        main = ttk.Frame(window, padding=12)
        main.pack(fill="both", expand=True)
        top = ttk.Frame(main)
        top.pack(fill="x")
        ttk.Button(top, text="启动对局", command=self.launch).pack(side="left")
        ttk.Button(top, text="打开记录目录", command=self.browse).pack(side="left", padx=6)
        ttk.Checkbutton(top, text="跟随实时搜索", variable=self.follow,
                        command=self.refresh).pack(side="left", padx=8)
        ttk.Checkbutton(top, text="记录模拟明细（下一手生效）", variable=self.rollouts,
                        command=self.set_rollouts).pack(side="left")
        self.searches = ttk.Combobox(main, state="readonly")
        self.searches.pack(fill="x", pady=(10, 4))
        self.searches.bind("<<ComboboxSelected>>", self.choose)
        ttk.Label(main, textvariable=self.summary).pack(anchor="w", pady=4)
        panes = ttk.Panedwindow(main, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes, padding=(12, 0))
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        self.tree = ttk.Treeview(left, columns=("state",), selectmode="browse")
        self.tree.heading("#0", text="搜索树 · 展开节点查看后续走法")
        self.tree.heading("state", text="当前统计")
        self.tree.column("#0", width=245)
        self.tree.column("state", width=195)
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("skip", foreground="#867767")
        self.tree.bind("<<TreeviewOpen>>", self.expand)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.inspect())
        self.tree.bind("<ButtonPress-1>", lambda _: self.follow.set(False))
        self.tree.bind("<KeyPress>", lambda _: self.follow.set(False))
        ttk.Label(right, text="节点局面", font=("", 13, "bold")).pack(anchor="w")
        self.canvas = tk.Canvas(right, width=310, height=310, background="#f3ead8", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=6)
        self.canvas.bind("<Configure>", lambda _: self.inspect())
        ttk.Label(right, textvariable=self.details, wraplength=330, justify="left").pack(anchor="w")
        self.log = tk.Text(right, height=4, width=28, wrap="word", state="disabled")
        ttk.Label(right, text="时间轴事件明细").pack(anchor="w")
        self.log.pack(fill="x", pady=6)
        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=(10, 0))
        for title, fn in [("上一步", lambda: self.advance(-1)),
                          ("下一步", lambda: self.advance(1)),
                          ("定位当前事件", self.locate), ("定位落子", self.locate_choice)]:
            ttk.Button(bar, text=title, command=fn).pack(side="left", padx=2)
        self.unit = ttk.Combobox(bar, values=("事件", "MCTS 迭代", "剪枝跳过"), width=10, state="readonly")
        self.unit.current(0)
        self.unit.pack(side="left", padx=(8, 2))
        self.unit.bind("<<ComboboxSelected>>", lambda _: self.update_index())
        entry = ttk.Entry(bar, textvariable=self.index, width=9)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _: self.seek_entry())
        self.scale = ttk.Scale(bar, from_=1, to=1, variable=self.slider,
                               command=lambda v: self.seek(round(float(v))))
        self.scale.pack(side="left", fill="x", expand=True, padx=8)
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll()

    def close(self):
        if self.after_id:
            self.window.after_cancel(self.after_id)
        if self.db:
            self.db.close()
        self.window.destroy()

    def launch(self):
        if self.game_process and self.game_process.poll() is None:
            messagebox.showinfo("搜索分析器", "已启动对局窗口。", parent=self.window)
            return
        folder = Path(resolve_path("records/analysis")) / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            folder.mkdir(parents=True)
            self.change_folder(folder)
            self.set_rollouts()
            self.game_process = subprocess.Popen([sys.executable, resolve_path("start.py")],
                env=dict(os.environ, ACBP_ANALYSIS_DIR=str(folder)),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            messagebox.showerror("无法启动", str(exc), parent=self.window)

    def browse(self):
        folder = filedialog.askdirectory(initialdir=resolve_path("records/analysis"))
        if folder:
            self.change_folder(Path(folder))
            self.rollouts.set((self.folder / "rollouts.enabled").exists())

    def change_folder(self, folder):
        self.folder = folder
        if self.db:
            self.db.close()
        self.db = self.path = None
        self.paths = []
        self.searches.set("")
        self.searches["values"] = ()
        self.tree.delete(*self.tree.get_children())
        self.canvas.delete("all")
        self.details.set("")
        self.write_log("")
        self.follow.set(True)
        self.summary.set(f"等待搜索记录 · {folder}")

    def set_rollouts(self):
        if self.folder:
            flag = self.folder / "rollouts.enabled"
            try:
                if self.rollouts.get():
                    flag.touch()
                else:
                    flag.unlink(missing_ok=True)
            except OSError as exc:
                self.rollouts.set(flag.exists())
                messagebox.showerror("无法更改采集设置", str(exc), parent=self.window)

    def choose(self, _):
        self.follow.set(False)
        self.load(self.paths[self.searches.current()])

    def load(self, path):
        db, info = open_record(path)
        if self.db:
            self.db.close()
        self.db, self.info, self.path = db, info, path
        self.auto_opened.clear()
        self.latest = self.cursor = 0
        self.tree.delete(*self.tree.get_children())
        self.searches.current(self.paths.index(path))
        self.update_time(True)
        if self.tree.exists("1"):
            self.tree.item("1", open=True)
            if not self.tree.selection():
                self.tree.selection_set("1")
            self.fill("1")

    def poll(self):
        try:
            self.refresh()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self.summary.set(f"等待读取记录 · {exc}")
        self.after_id = self.window.after(300, self.poll)

    def refresh(self):
        if not self.folder:
            return
        paths = sorted(self.folder.glob("*.sqlite"), reverse=True)
        if paths != self.paths:
            self.paths = paths
            self.searches["values"] = [p.stem.rsplit("_", 1)[0] for p in paths]
        if paths and (self.db is None or self.follow.get() and paths[0] != self.path):
            self.load(paths[0])
        elif self.db:
            self.update_time(self.follow.get())

    def update_time(self, live):
        self.latest = self.db.execute("select max(step) from events").fetchone()[0] or 0
        self.scale.configure(to=max(1, self.latest))
        if live and self.latest != self.cursor:
            self.show(self.latest)

    def seek_entry(self):
        try:
            index = int(self.index.get())
            if self.unit.current() > 0 and self.db:
                kind = ("模拟回传", "剪枝跳过")[self.unit.current()-1]
                row = self.db.execute("select step from events where kind=? order by step limit 1 offset ?",
                                      (kind, max(0, index-1))).fetchone()
                if row:
                    self.seek(row[0])
                    self.locate()
                else:
                    self.summary.set("当前搜索没有对应序号的事件")
            else:
                self.seek(index)
        except ValueError:
            self.update_index()

    def update_index(self):
        index = self.cursor
        if self.db and self.unit.current() > 0:
            kind = ("模拟回传", "剪枝跳过")[self.unit.current()-1]
            index = self.db.execute("select count(*) from events where kind=? and step<=?",
                                    (kind, self.cursor)).fetchone()[0]
        self.index.set(str(index))

    def advance(self, delta):
        if not self.db:
            return
        if self.unit.current() == 0:
            self.seek(self.cursor + delta)
        else:
            kind = ("模拟回传", "剪枝跳过")[self.unit.current()-1]
            query = ("select min(step) from events where step>? and kind=?" if delta > 0 else
                     "select max(step) from events where step<? and kind=?")
            step = self.db.execute(query, (self.cursor, kind)).fetchone()[0]
            if step is not None:
                self.seek(step)
        self.locate()

    def seek(self, step):
        if self.db:
            self.follow.set(False)
            self.show(max(1, min(step, self.latest)))

    def show(self, step):
        self.cursor = step
        self.update_index()
        self.slider.set(step)
        row = self.db.execute("select node,kind,data from events where step=?", (step,)).fetchone()
        if row is None:
            return
        self.event_node, kind, data = row
        data = json.loads(data)
        side = "黑方" if self.info["player"] == 1 else "白方"
        self.summary.set(f'第 {self.info["ply"]+1} 手 · {side} {self.info["algo"]}     '
                         f'事件 {step} / {self.latest}    {kind}')
        self.write_log(self.describe(data))
        self.fill("")
        if self.follow.get():
            chain = self.ancestors(self.event_node)
            active = {str(n) for n, _, _ in chain[:-1]}
            for old in self.auto_opened - active:
                if self.tree.exists(old):
                    self.tree.item(old, open=False)
            self.auto_opened = active
            self.reveal(self.event_node)
        else:
            self.inspect()

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)
        self.log.configure(state="disabled")

    def coord(self, move):
        def square(r, c):
            return f"{chr(65+c)}{self.info['size']-r}"
        if self.info["game"] == "chess":
            return "→".join(square(*decode_sq(i)) for i in move)
        return square(*move)

    def describe(self, data):
        labels = dict(alpha="α", beta="β", role="类型", bound="界", score="评分", visits="访问", iteration="迭代",
                      wins="累计收益", outcome="模拟收益", note="说明", best="领先走法", move="选步")
        values = []
        if data.get("visits"):
            values.append(f'估计胜率 {data["wins"]/data["visits"]:.1%}')
        for k, v in data.items():
            if v is None or v == "":
                continue
            if k == "rollout":
                values.append("模拟走法 " + " ".join(map(self.coord, v)))
            else:
                if k in ("move", "best"):
                    v = self.coord(v)
                elif isinstance(v, float):
                    v = f"{v:.3g}"
                values.append(f"{labels.get(k,k)} {v}")
        return "  ".join(values)

    def state(self, node, step):
        row = self.db.execute("select data from stats where node=? and step<=? order by step desc limit 1",
                              (node, step)).fetchone()
        return self.describe(json.loads(row[0])) if row else ""

    def fill(self, parent):
        rows = self.db.execute("select id,move,label from nodes where parent=? and id<=? order by id",
                               (int(parent or 0), self.cursor)).fetchall()
        ids = {str(row[0]) for row in rows}
        for iid in self.tree.get_children(parent):
            if iid not in ids:
                self.tree.delete(iid)
        for node, raw, label in rows:
            iid = str(node)
            move = json.loads(raw)
            title = f"{self.coord(move)}  {label}" if move is not None else label
            values = (self.state(node, self.cursor),)
            if self.tree.exists(iid):
                self.tree.item(iid, values=values)
            else:
                self.tree.insert(parent, "end", iid=iid, text=title, values=values,
                                 tags=("skip",) if label == "剪枝跳过" else ())
            if self.tree.item(iid, "open"):
                self.fill(iid)
            else:
                dummy = "stub"+iid
                has_child = self.db.execute("select 1 from nodes where parent=? and id<=? limit 1",
                                            (node, self.cursor)).fetchone()
                if has_child and not self.tree.get_children(iid):
                    self.tree.insert(iid, "end", iid=dummy)
                elif not has_child:
                    for descendant in self.tree.get_children(iid):
                        self.tree.delete(descendant)

    def expand(self, _):
        node = self.tree.focus()
        if node.isdigit():
            self.fill(node)

    def ancestors(self, node):
        result = []
        while node:
            parent, raw, label = self.db.execute(
                "select parent,move,label from nodes where id=?", (node,)).fetchone()
            result.append((node, json.loads(raw), label))
            node = parent
        return result[::-1]

    def reveal(self, node):
        for ancestor, _, _ in self.ancestors(node)[:-1]:
            self.tree.item(str(ancestor), open=True)
            self.fill(str(ancestor))
        iid = str(node)
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self.inspect()

    def locate(self):
        if self.db:
            self.reveal(self.event_node)

    def locate_choice(self):
        if not self.db:
            return
        row = self.db.execute("select step,data from events where kind='完成' order by step desc limit 1").fetchone()
        if not row:
            self.summary.set("本次搜索尚无最终落子记录")
            return
        self.seek(row[0])
        move = json.loads(row[1]).get("move")
        parent = 1
        if self.info["algo"] == "alphabeta":
            parent = self.db.execute("select max(id) from nodes where parent=1").fetchone()[0]
        children = self.db.execute("select id,move from nodes where parent=?", (parent,))
        node = next((n for n, m in children if json.loads(m) == move), 1)
        self.reveal(node)

    def inspect(self):
        selection = self.tree.selection()
        if not self.db or not selection or not selection[0].isdigit():
            self.canvas.delete("all")
            self.details.set("")
            return
        node = int(selection[0])
        chain = self.ancestors(node)
        moves = [m for _, m, _ in chain if m is not None]
        entry = self.state(node, node)
        current = self.state(node, self.cursor)
        self.details.set(" › ".join(map(self.coord, moves)) + "\n" + chain[-1][2] +
                         ("    进入：" + entry if entry and entry != current else "") + "\n" + current)
        cells = position(self.info, moves)
        self.canvas.delete("all")
        rows, cols = len(cells), len(cells[0])
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        unit = max(1, min((w-20)/cols, (h-20)/rows))
        ox, oy = (w-cols*unit)/2, (h-rows*unit)/2
        chess = self.info["game"] == "chess"
        for r, line in enumerate(cells):
            for c, value in enumerate(line):
                x, y = ox+c*unit, oy+r*unit
                self.canvas.create_rectangle(x,y,x+unit,y+unit,outline="#bbae92")
                if value:
                    dark = (piece_side(value) if chess else value) == 1
                    self.canvas.create_oval(x+2,y+2,x+unit-2,y+unit-2,
                                            fill="#323431" if dark else "#fffdf5", outline="#55534d")
                    if chess:
                        self.canvas.create_text(x+unit/2,y+unit/2,text=piece_name(value),
                                                fill="white" if dark else "black")


if __name__ == "__main__":
    root = tk.Tk()
    Analyzer(root, Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    root.mainloop()
