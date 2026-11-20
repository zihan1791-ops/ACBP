"""Regression checks for complete desktop recordings and timeline navigation."""
import json
import random
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

from ai.factory import create_ai
from analyzer import Analyzer, open_record, position
from config.args import load_config
from core.base_board import BLACK
from core.othello.board import OthelloBoard
from ui.ai_runner import AiRunner


def settings():
    return load_config(["--ab-depth", "4", "--ab-time", "0",
                        "--mcts-iterations", "48", "--mcts-time", "0"])


class SearchTreeTests(unittest.TestCase):
    def test_record_all_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "rollouts.enabled").touch()
            for algo in ("mcts", "alphabeta"):
                ai = create_ai(algo, BLACK, settings())
                board = OthelloBoard(8)
                random.seed(17)
                expected = ai.select_move(board)
                ai.analysis_dir = folder
                random.seed(17)
                selected = ai.select_move(board)
                self.assertEqual(selected, expected)
                path = next(folder.glob(f"*_{algo}_*.sqlite"))
                db, info = open_record(path)
                try:
                    last = db.execute("select kind,data from events order by step desc limit 1").fetchone()
                    self.assertEqual(last[0], "完成")
                    self.assertEqual(json.loads(last[1])["move"], list(selected))
                    positions = {0: []}
                    for node, parent, raw, label in db.execute("select * from nodes order by id"):
                        move = json.loads(raw)
                        moves = positions[parent] + ([move] if move is not None else [])
                        positions[node] = moves
                        self.assertTrue(position(info, moves))
                    self.assertGreater(max(map(len, positions.values())), 2)
                    if algo == "mcts":
                        iterations = list(db.execute("select data from events where kind='模拟回传'"))
                        self.assertEqual(len(iterations), 48)
                        self.assertTrue(json.loads(iterations[0][0])["rollout"])
                        stat = db.execute("select data from stats where node=1 order by step desc").fetchone()
                        self.assertEqual(json.loads(stat[0])["visits"], 48)
                    else:
                        count = db.execute("select count(*) from nodes where label in ('MIN','MAX')").fetchone()[0]
                        self.assertEqual(count, ai.think.done)
                        self.assertTrue(db.execute("select 1 from nodes where label='剪枝跳过'").fetchone())
                finally:
                    db.close()

    def test_worker_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = AiRunner()
            try:
                cfg = dict(settings().to_dict(), analysis_dir=folder)
                self.assertTrue(runner.submit(OthelloBoard(8), "alphabeta", BLACK, cfg))
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    msg = runner.poll()
                    if msg and msg[0] in ("done", "error"):
                        break
                    time.sleep(.01)
                self.assertTrue(msg and msg[0] == "done", msg)
                db, info = open_record(next(Path(folder).glob("*.sqlite")))
                try:
                    move = db.execute("select data from events where kind='完成'").fetchone()[0]
                    self.assertEqual(json.loads(move)["move"], list(msg[2]))
                finally:
                    db.close()
            finally:
                runner.shutdown()

    def test_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ai = create_ai("alphabeta", BLACK, settings())
            ai.analysis_dir = folder
            move = ai.select_move(OthelloBoard(8))
            root = tk.Tk()
            root.withdraw()
            viewer = Analyzer(root, folder)
            try:
                root.update_idletasks()
                self.assertGreater(viewer.latest, 50)
                viewer.locate_choice()
                node = int(viewer.tree.selection()[0])
                self.assertEqual(viewer.ancestors(node)[-1][1], list(move))
                viewer.seek(1)
                self.assertFalse(viewer.tree.get_children("1"))
                viewer.unit.current(2)
                viewer.advance(1)
                self.assertEqual(viewer.ancestors(viewer.event_node)[-1][2], "剪枝跳过")
                viewer.follow.set(True)
                viewer.refresh()
                self.assertEqual(viewer.cursor, viewer.latest)
            finally:
                viewer.close()


if __name__ == "__main__":
    unittest.main()
