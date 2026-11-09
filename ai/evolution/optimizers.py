# -*- coding: utf-8 -*-
"""
四种群体优化算法的下棋 AI 实现。

全部继承 EvolutionaryAI，对外只有 select_move(board, on_progress)；
每个类只在 _step() 里实现自己的一代算子：
    ImprovedGeneticAI        改进遗传算法（精英保留 + 自适应变异 + 停滞重启）
    DifferentialEvolutionAI  差分进化 DE/rand/1/bin
    ParticleSwarmAI          粒子群 PSO（惯性权重线性递减）
    ArtificialBeeColonyAI    人工蜂群 ABC（雇佣蜂 / 跟随蜂 / 侦察蜂）

连续算子产生的分量统一按模 1 回绕到 [0,1)，由 kernel.decode 负责
翻译成合法着法，算子层不需要知道棋盘规则。
"""

from typing import List

from .base import EvolutionaryAI
from .kernel import VERY_BAD


class ImprovedGeneticAI(EvolutionaryAI):
    """改进遗传算法：锦标赛选择 + 均匀交叉 + 自适应高斯变异。"""

    name = "iga"
    display_name = "改进GA"
    optimizer = "改进遗传算法"

    def __init__(self, player, config) -> None:
        super().__init__(player, config)
        self.elite = max(1, int(getattr(config, "evo_elite", 2)))
        self.stall_limit = max(2, int(getattr(config, "evo_stall_limit", 6)))
        self.base_mutation = 0.35

    def _tournament(self, pop, scores):
        k = min(3, len(pop))
        best = max(self.rng.sample(range(len(pop)), k),
                   key=lambda i: scores[i])
        return pop[best]

    def _step(self, pop, scores, board, gen):
        n = len(pop)
        order = sorted(range(n), key=lambda i: -scores[i])
        mutation = self.base_mutation * (1.0 - 0.8 * gen / max(1, self.generations))

        # 停滞重启：连续多代无改进时只保留最强个体，其余重新随机化
        keep = 1 if self._stall >= self.stall_limit else self.elite
        new_pop = [list(pop[i]) for i in order[:keep]]

        while len(new_pop) < n:
            p1 = self._tournament(pop, scores)
            p2 = self._tournament(pop, scores)
            child = [p1[d] if self.rng.random() < 0.5 else p2[d]
                     for d in range(self.horizon)]
            for d in range(self.horizon):
                if self.rng.random() < mutation:
                    child[d] = (child[d] + self.rng.gauss(0.0, 0.15)) % 1.0
            new_pop.append(child)

        return new_pop, self._assess_population(board, new_pop)


class DifferentialEvolutionAI(EvolutionaryAI):
    """差分进化：DE/rand/1/bin，边界按模 1 回绕。"""

    name = "de"
    display_name = "差分进化"
    optimizer = "差分进化 DE"

    def __init__(self, player, config) -> None:
        super().__init__(player, config)
        self.F = float(getattr(config, "evo_de_f", 0.6))
        self.CR = float(getattr(config, "evo_de_cr", 0.85))

    def _step(self, pop, scores, board, gen):
        n = len(pop)
        new_pop: List[List[float]] = []
        new_scores: List[float] = []

        for i in range(n):
            if self.timer.timeout:
                new_pop.append(list(pop[i]))
                new_scores.append(scores[i])
                continue
            others = [j for j in range(n) if j != i]
            a, b, c = self.rng.sample(others, 3)
            jrand = self.rng.randrange(self.horizon)
            trial = []
            for d in range(self.horizon):
                if self.rng.random() < self.CR or d == jrand:
                    trial.append((pop[a][d] + self.F * (pop[b][d] - pop[c][d])) % 1.0)
                else:
                    trial.append(pop[i][d])
            fs = self._assess(board, trial)
            if fs >= scores[i]:
                new_pop.append(trial)
                new_scores.append(fs)
            else:
                new_pop.append(list(pop[i]))
                new_scores.append(scores[i])
        return new_pop, new_scores


class ParticleSwarmAI(EvolutionaryAI):
    """粒子群：全局版 PSO，惯性权重随代数从 0.9 线性降到 0.4。"""

    name = "pso"
    display_name = "粒子群"
    optimizer = "粒子群 PSO"

    def _step(self, pop, scores, board, gen):
        n = len(pop)
        if self._velocity is None:
            self._velocity = [[self.rng.uniform(-0.1, 0.1)
                               for _ in range(self.horizon)] for _ in pop]
            self._pbest = [list(v) for v in pop]
            self._pbest_scores = list(scores)

        w = 0.9 - 0.5 * min(1.0, gen / max(1, self.generations))
        g = max(range(n), key=lambda i: self._pbest_scores[i])
        gbest = self._pbest[g]

        new_pop: List[List[float]] = []
        for i in range(n):
            vel, pos = self._velocity[i], pop[i]
            nv, nx = [], []
            for d in range(self.horizon):
                r1, r2 = self.rng.random(), self.rng.random()
                v = (w * vel[d]
                     + 1.6 * r1 * (self._pbest[i][d] - pos[d])
                     + 1.6 * r2 * (gbest[d] - pos[d]))
                v = max(-0.3, min(0.3, v))
                nv.append(v)
                nx.append((pos[d] + v) % 1.0)
            self._velocity[i] = nv
            new_pop.append(nx)

        new_scores = self._assess_population(board, new_pop)
        for i, s in enumerate(new_scores):
            if s > self._pbest_scores[i]:
                self._pbest_scores[i] = s
                self._pbest[i] = list(new_pop[i])
        return new_pop, new_scores


class ArtificialBeeColonyAI(EvolutionaryAI):
    """人工蜂群：雇佣蜂邻域搜索 + 跟随蜂轮盘赌 + 侦察蜂重置。"""

    name = "abc"
    display_name = "人工蜂群"
    optimizer = "人工蜂群 ABC"

    def __init__(self, player, config) -> None:
        super().__init__(player, config)
        self.limit = max(2, int(getattr(config, "evo_abc_limit", 5)))

    def _perturb(self, pop, i):
        v = list(pop[i])
        d = self.rng.randrange(self.horizon)
        k = self.rng.randrange(len(pop))
        phi = self.rng.uniform(-1.0, 1.0)
        v[d] = (v[d] + phi * (v[d] - pop[k][d])) % 1.0
        return v

    def _step(self, pop, scores, board, gen):
        n = len(pop)
        if self._trials is None:
            self._trials = [0] * n

        # 雇佣蜂：每个食物源做一次邻域扰动
        for i in range(n):
            if self.timer.timeout:
                break
            cand = self._perturb(pop, i)
            fs = self._assess(board, cand)
            if fs > scores[i]:
                pop[i], scores[i], self._trials[i] = cand, fs, 0
            else:
                self._trials[i] += 1

        # 跟随蜂：按适应度轮盘赌选择更值得开发的食物源
        valid = [s for s in scores if s > VERY_BAD]
        base = min(valid) if valid else 0.0
        weights = [(s - base + 1.0) if s > VERY_BAD else 0.0 for s in scores]
        total = sum(weights)
        if total > 0:
            for _ in range(n):
                if self.timer.timeout:
                    break
                r = self.rng.random() * total
                acc, pick = 0.0, 0
                for i, w in enumerate(weights):
                    acc += w
                    if acc >= r:
                        pick = i
                        break
                cand = self._perturb(pop, pick)
                fs = self._assess(board, cand)
                if fs > scores[pick]:
                    pop[pick], scores[pick], self._trials[pick] = cand, fs, 0
                else:
                    self._trials[pick] += 1

        # 侦察蜂：长期未改进的食物源直接放弃
        for i in range(n):
            if self._trials[i] >= self.limit:
                pop[i] = self._random_vector()
                scores[i] = self._assess(board, pop[i])
                self._trials[i] = 0
        return pop, scores
