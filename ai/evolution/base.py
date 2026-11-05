# -*- coding: utf-8 -*-
"""
进化类下棋 AI 的统一基类。

对外契约与 MCTS / Alpha-Beta 完全一致：
    select_move(board, on_progress=None) -> (row, col) | None

种群初始化、适应度评估、时间预算、思考状态可视化、强制预检全部在此闭环；
子类只实现 _step() —— 即各自算法的进化算子。四种算法共用同一套
「棋局 → 个体 → 适应度 → 落子」内部管线，外部层完全无感知。
"""

import random
from typing import List, Optional, Tuple

from ai.base_ai import BaseAI
from utils.helpers import MoveTimer
from .kernel import (VERY_BAD, WIN_SCORE, current_candidates, fitness,
                     forced_move, prior_vectors)


class EvolutionaryAI(BaseAI):
    """群体优化下棋 AI 的公共骨架。"""

    name = "evolution"
    display_name = "进化算法"
    optimizer = "群体优化"

    def __init__(self, player, config) -> None:
        super().__init__(player, config)
        # getattr 同时兼容主进程 Config 与多进程 worker 的 SimpleNamespace
        self.pop_size = max(4, int(getattr(config, "evo_population", 30)))
        self.generations = max(1, int(getattr(config, "evo_generations", 50)))
        self.horizon = max(1, int(getattr(config, "evo_horizon", 6)))
        self.time_limit = float(getattr(config, "evo_time", 8.0))
        self.rng = random.Random(getattr(config, "random_seed", None))
        self.timer = MoveTimer(self.time_limit)
        self._reset_search()

    # -------------------- 搜索状态 --------------------

    def _reset_search(self) -> None:
        self._evaluated = 0
        self._best_score = VERY_BAD
        self._best_vec: Optional[List[float]] = None
        self._best_move: Optional[Tuple[int, int]] = None
        self._move_scores = {}
        self._last_best = VERY_BAD
        self._stall = 0
        # 供 PSO / ABC 复用的跨代状态
        self._velocity = None
        self._pbest = None
        self._pbest_scores = None
        self._trials = None

    def _assess(self, board, vector) -> float:
        """评估一个个体，并维护全局最优与「每个首步的最好分」。"""
        if self.timer.timeout:
            return VERY_BAD
        score, first = fitness(board, vector, self.player, self.horizon)
        self._evaluated += 1
        if first is None:
            return score
        if score > self._move_scores.get(first, VERY_BAD):
            self._move_scores[first] = score
        if score > self._best_score:
            self._best_score = score
            self._best_vec = list(vector)
            self._best_move = first
        return score

    def _random_vector(self) -> List[float]:
        return [self.rng.random() for _ in range(self.horizon)]

    def _init_population(self, board) -> List[List[float]]:
        pop = prior_vectors(board, self.player, self.horizon, self.rng,
                            min(self.pop_size // 3, 10))
        while len(pop) < self.pop_size:
            pop.append(self._random_vector())
        return pop[:self.pop_size]

    def _top_moves(self):
        ranked = sorted(self._move_scores.items(),
                        key=lambda kv: -kv[1])[:3]
        return [(m, i + 1, s) for i, (m, s) in enumerate(ranked)]

    def _publish(self, gen: int, note: str = "") -> None:
        self.think.done = self._evaluated
        self.think.total = self.pop_size * self.generations
        self.think.depth = gen
        self.think.max_depth = self.generations
        self.think.elapsed = self.timer.elapsed()
        self.think.phase = "%s · 第 %d/%d 代" % (
            self.optimizer, gen, self.generations)
        self.think.best_move = self._best_move
        self.think.best_value = (self._best_score
                                if self._best_score > VERY_BAD else 0.0)
        self.think.top_moves = self._top_moves()
        self.think.note = note
        if self._best_score > self._last_best + 1e-9:
            self._last_best = self._best_score
            self._stall = 0
        else:
            self._stall += 1

    # -------------------- 对外唯一入口 --------------------

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        self._begin_think()
        self._reset_search()
        self.timer.start()

        legal = board.get_legal_moves()
        if not legal:
            self.think.note = "无合法步，停一手"
            self.think.finish()
            self._emit(on_progress)
            return None

        forced, note = forced_move(board, self.player)
        if forced is not None:
            self.think.phase = "强制预检"
            self.think.note = note
            self.think.best_move = forced
            self.think.best_value = WIN_SCORE
            self.think.done = self.think.total = 1
            self.think.top_moves = [(forced, 1, WIN_SCORE)]
            self.think.elapsed = self.timer.elapsed()
            self.think.finish()
            self._emit(on_progress)
            return forced

        pop = self._init_population(board)
        scores = [self._assess(board, v) for v in pop]
        self._publish(0, "棋理先验已注入")
        self._emit(on_progress)

        for gen in range(1, self.generations + 1):
            if self.timer.timeout:
                break
            pop, scores = self._step(pop, scores, board, gen)
            self._publish(gen)
            self._emit(on_progress)

        move = self._best_move
        if move is None or move not in legal:
            cands = current_candidates(board)
            move = cands[0] if cands else legal[0]
        self.think.best_move = move
        if self.timer.timeout:
            self.think.note = "预算用尽，返回当前最优"
        else:
            self.think.note = "搜索完成"
        self.think.finish()
        self._emit(on_progress)
        return move

    def _step(self, pop, scores, board, gen):
        """由子类实现：执行一代进化，返回 (新种群, 新适应度)。"""
        raise NotImplementedError
