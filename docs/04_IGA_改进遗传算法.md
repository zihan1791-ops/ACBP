# 04　IGA 与「进化类四兄弟」的公共底座

> 把一串走法当成个体，让好的繁殖、差的淘汰；逐行读 `ai/evolution/`

**编号 04　|　难度：进阶　|　建议阅读：35 分钟　|　前置：第 00 篇（统一接口）；第 03 篇有助于理解合法步**

[← 返回文档导航](README.md)　|　上一篇：[03 随机基线](03_Random_随机基线.md)　|　下一篇：[05 DE 差分进化](05_DE_差分进化算法.md)

> **30 秒速览：** IGA / DE / PSO / ABC 四种算法共用同一套骨架：用一个实数向量表示「接下来几步怎么走」，把向量解码成一串合法落子，推演完给局面打分（适应度），再让一批向量互相竞争、逐代改进。这一篇先把**公共底座** `ai/evolution/base.py` + `kernel.py` 逐段读透，再讲 IGA 独有的 `_step()`；后面 05—07 只换「怎么产生下一代」。

> **源码快照说明：** 代码片段基于 **2026-11-10** 源码，均为**节选**；行号仅供对照，**函数名才是稳定定位**。

## 这一篇的目录

1. [1. 这一篇讲什么](#1-这一篇讲什么)
2. [2. 先用直觉理解](#2-先用直觉理解)
3. [3. 跟着代码走一遍](#3-跟着代码走一遍)
4. [4. 名词速查](#4-名词速查)
5. [5. 源码逐段精读](#5-源码逐段精读)
6. [6. 代码模块地图](#6-代码模块地图)
7. [7. 动手试一试](#7-动手试一试)
8. [8. 常见疑问与已知限制](#8-常见疑问与已知限制)

---

## 1. 这一篇讲什么

一句话：进化类 AI 不一步步推演博弈树，而是养一大批「候选走法序列」，用打分和迭代把它们越改越好。

读完你应该能回答：

- 一个实数向量，怎么就变成了一串**合法**的棋步？
- 「适应度」在给什么打分，对手被怎么简化处理了？
- 四种算法到底共享了什么，IGA 又「改进」在哪？

**这一篇会带你读的文件：** `ai/evolution/base.py`（公共基类）、`ai/evolution/kernel.py`（解码与适应度）、`ai/evolution/optimizers.py`（四种 `_step()`）、`ai/accel/batch.py`（批量打分）、`ai/candidates.py`、`ai/evaluator.py`、`config/settings.py`。

> **初学者提示：** 这一篇是 04—07 四篇里最重要的一篇。把第 2、3 节的「向量 → 合法步 → 打分」链条弄懂，后面三篇只是在换「怎么改写纸条」。

## 2. 先用直觉理解

假设你要规划「接下来 6 步的下法」，但不可能穷举所有组合。于是你先随手写出 50 张纸条，每张写一套下法；把每张纸条在棋盘上摆一遍，看最后局面好不好，给个分；然后留下分数高的纸条，参考它们改写分数低的，再摆一遍……重复几百轮，最后挑最好的那张纸条的第一步来下。

四种进化算法的区别只在「怎么改写纸条」：IGA 用交叉变异，DE 用个体间的差分，PSO 让大家向历史最优靠拢，ABC 用蜜蜂分工做邻域搜索。

> **初学者提示：** 关键巧思是——纸条上写的**不是具体坐标**，而是一串 0~1 的小数。解码时才按「当前局面的合法步清单」换算成坐标，所以无论怎么改小数，都不会产生非法着法。

## 3. 跟着代码走一遍

> **这一节是整篇最关键的部分。** 设 `EVO_HORIZON = 6`（推演 6 步）、`EVO_POPULATION = 50`（50 个个体）、`EVO_GENERATIONS = 500`（最多 500 代）、`EVO_TIME_LIMIT = 20.0` 秒。下面按真实执行顺序走 9 步。

### 先收好这张「函数名对照表」

| 函数名（英文） | 中文作用（它到底干了什么） | 输入 → 输出 |
| --- | --- | --- |
| `EvolutionaryAI.select_move()` | 四种算法共用的总入口：初始化 → 评估 → 逐代进化 → 返回最优首步 | 棋盘 + 回调 → `(row, col)` |
| `_reset_search()` | 清空本步的所有跨代状态（缓存、最优、停滞计数、PSO/ABC 状态） | 无 → 状态归零 |
| `_init_population()` | 造初始种群：先验种子 + 随机向量补齐 | 棋盘 → 50 个向量 |
| `prior_vectors()` | 把成四点 / 防守点 / 高分候选编码成「第一步指向该点」的种子 | 棋盘 + 数量 → 若干向量 |
| `decode()` | 把向量解码成「我走一步 → 对手应一步」的合法推演序列 | 棋盘 + 向量 → `(首步, 末局面, 步数)` |
| `current_candidates()` | 返回当前局面的候选步（裁剪结果为空时退回全部合法步） | 局面 → 坐标列表 |
| `_heuristic_reply()` | 一层贪心对手模型：在前 12 个候选里挑棋理分最高的一手应 | 局面 → 已落子 / `False` |
| `fitness()` | 算适应度：终局给胜负奖励，未终局给局面评估分 | 棋盘 + 向量 → `(分数, 首步)` |
| `_assess_population()` | 整代解码 + 批量打分，逐个记入缓存与全局最优 | 种群 → 分数列表 |
| `batch_scores()` | 用 numpy / 可选 CUDA 一次性给一批末局面打分 | 局面列表 → 分数列表或 `None` |
| `_record()` | 记录「每个首步的最好分」与「全局最优个体」 | 向量 + 分数 + 首步 → 分数 |
| `_publish()` | 把代数、后端、最优步、Top3 写进 `ThinkState`，并更新停滞计数 | 代数 → 界面可见状态 |
| `_step()` | **子类实现**：产生下一代种群 | 种群 + 分数 → 新种群 + 新分数 |
| `ImprovedGeneticAI._tournament()` | 锦标赛选择：随机抽 3 个个体，取分数最高的当父代 | 种群 + 分数 → 一个向量 |

### 第 1 步：读预算，建一个独立的随机数发生器

**在干什么：** 把这次搜索要用到的参数准备好。

**函数具体做什么：** `EvolutionaryAI.__init__()` 里用 `getattr(config, "evo_population", 30)` 这类写法读配置——**注意这里写的 30 / 50 / 6 / 8.0 只是「配置缺字段时的兜底」**，实际值由 `config/settings.py` 提供，分别是 50 / 500 / 6 / 20.0。源码注释解释了为什么用 `getattr`：主进程传的是 `Config` 对象，多进程 worker 传的是 `SimpleNamespace`，两者都要兼容。此外 `self.rng = random.Random(getattr(config, "random_seed", None))` 建了一个**独立的随机实例**（与第 03 篇的全局 `random` 不同），`self._backend = backend_name()` 只探测一次打分后端（numpy / cuda / cpu）。

**输入 → 输出：** `cfg` → `pop_size=50`、`generations=500`、`horizon=6`、`time_limit=20.0`、`rng`。

**为什么：** 四种算法共用一组 `EVO_*` 预算，横向 PK 才公平；独立 `rng` 让 `--seed` 能复现且不与别的模块互相干扰。

### 第 2 步：按棋种收紧推演视野，并清空跨代状态

**在干什么：** 不同棋种推演一步的成本差很多，要先调整「看几步」。

**函数具体做什么：** `select_move()` 开头判断：象棋 `ChessBoard` 的将军过滤很贵，`horizon` 压到至多 3；19 路围棋算气很贵，压到至多 4。然后 `_reset_search()` 把 `_evaluated`（已评估个体数）、`_fitness_cache`（适应度缓存）、`_best_score` / `_best_vec` / `_best_move`、`_move_scores`（每个首步的最好分）、`_last_best` / `_stall`（停滞计数），以及 PSO / ABC 用的 `_velocity` / `_pbest` / `_pbest_scores` / `_trials` **全部清空**。

**输入 → 输出：** 当前棋盘 + 配置 → 一个干净的新搜索状态；`timer.start()` 记下开始时刻。

**为什么：** 不同棋局的合法步清单完全不同，上一局的速度、最优向量、停滞计数在这一局没有任何意义，沿用只会把搜索带偏。

### 第 3 步：无合法步 / 强制预检，能省则省

**在干什么：** 处理边界与确定性战术。

**函数具体做什么：** `legal = board.get_legal_moves()`，为空就写 `think.note = "无合法步，停一手"` 后返回 `None`。接着调 `kernel.forced_move(board, self.player)`，它转发给 `ai/candidates.py · gomoku_forced_move()`（与 MCTS / Alpha-Beta 同一份四层预检）；命中就把 `think.phase = "强制预检"`、`best_value = WIN_SCORE`、`top_moves` 只放这一手，然后**直接返回**。

**输入 → 输出：** 棋盘 + 本方 → 一个坐标（命中时），或 `None`（无合法步）。

**为什么：** 一手成五这种确定结论不该交给带随机性的种群搜索。

### 第 4 步：造初始种群，先塞几张「好纸条」

**在干什么：** 生成 50 个个体（每个是长度 6 的 `[0,1)` 实数向量）。

**函数具体做什么：** `_init_population()` 先调 `kernel.prior_vectors()`：它取当前候选步列表，把五子棋的进攻点 / 防守点、以及 `sort_moves_by_heuristic()` 排序前 `SEED_TOP = 8` 的高分点，编码成 `[ (该点索引 + 0.5)/候选数, 后面几维随机 ]` 这样的向量（数量取 `min(pop_size // 3, 10)`）；剩下不够 50 个的部分用 `_random_vector()`（每维 `rng.random()`）补齐。

**输入 → 输出：** 棋盘 → `pop = [[0.13, 0.72, ...], ...]`，共 50 个长度 6 的向量。

**为什么：** 纯随机起步会浪费大量预算在明显无关的位置；先验种子让搜索「从好棋起步」。

### 第 5 步：整代解码并批量打分（最核心的一步）

**在干什么：** 把 50 张纸条各摆一遍，得到 50 个分数。

**函数具体做什么：** `_assess_population()` 先对整代调 `decode(board, v, self.player, self.horizon)`。`decode()` 的逻辑是：复制棋盘 → 对每一维 `v = vector[j]` 算 `idx = int(v * len(cands))`（`cands` 是**那一刻**的候选步列表）→ 走 `cands[idx]` → 调 `_heuristic_reply()` 让对手按棋理分应一手 → 局面更新、重新生成候选清单 → 下一维。返回 `(首步, 末局面, 我方步数)`。末局面若已分胜负，用 `WIN_SCORE - steps`（赢得越快分越高）或 `-WIN_SCORE + steps`；否则交给 `evaluate()`。项目把一批末局面交给 `ai/accel/batch.py · batch_scores()` 用 numpy 一次性打分，后端不可用时逐个回退 `evaluate()`。

**输入 → 输出：** 50 个向量 → 50 个分数 `scores`，同时 `_move_scores` 记下每个首步见过的最好分、`_best_move` 指向全局最优个体的第一步。

**为什么：** 整代批量比「一个个 Python 循环打分」快得多；`_record()` 同时维护「首步 → 最好分」，最终才能从最优个体还原出要下的那一步。

### 第 6 步：把进度播报出去，再进入逐代循环

**在干什么：** 让界面看到「第几代、用的什么后端、当前最佳步」。

**函数具体做什么：** `_publish(0, "棋理先验已注入")` 把 `_evaluated` 写进 `think.done`、`pop_size * generations` 写进 `think.total`、代数写进 `think.depth`、后端名写进 `phase`，并把 `_top_moves()`（按 `_move_scores` 排序的 Top3）写进 `think.top_moves`。同时比较 `_best_score` 与 `_last_best`：有进步就把 `_stall` 归零，否则 `_stall += 1`。随后 `_emit()` 推给界面。

**输入 → 输出：** 第 0 代状态 → 界面进度条 + 候选高亮。

**为什么：** 与 MCTS / Alpha-Beta 共用同一份 `ThinkState`，界面不需要为进化算法写特例。

### 第 7 步：主循环里，把「下一代怎么来」交给子类

**在干什么：** 重复 500 代（或 20 秒到点）。

**函数具体做什么：** `for gen in range(1, self.generations + 1):` 每代先 `if self.timer.timeout: break`，再调 `self._step(pop, scores, board, gen)` —— 这是基类里的**抽象方法** `raise NotImplementedError`，四种子类各自实现。返回新的 `(pop, scores)` 后 `_publish(gen)` + `_emit()`。

**输入 → 输出：** 旧种群 + 分数 → 新种群 + 新分数。

**为什么：** 「棋局 → 个体 → 适应度 → 落子」这条管线四种算法完全一样，差异只有「怎么改写纸条」，把它抽成一个方法是最自然的分工。

### 第 8 步：IGA 的一代——选父代、交叉、变异、停滞重启

**在干什么：** 用「好纸条」繁殖出新纸条。

**函数具体做什么：** `ImprovedGeneticAI._step()` 先按分数降序得到 `order`，算自适应变异率 `mutation = 0.35 * (1 - 0.8 * gen / generations)`（越到后期改动越小）；`keep = 1 if self._stall >= self.stall_limit else self.elite` —— 若连续 6 代没进步，只留最强的 1 个、其余全部重来（**停滞重启**）；否则保留 `EVO_ELITE = 2` 个精英直接保送。剩下的空位由 `_tournament()` 随机抽 3 个取最高分当父代，两个父代逐维五五开做**均匀交叉**，再以 `mutation` 概率给每维加一个 `gauss(0, 0.15)` 的高斯扰动并 `% 1.0` 回绕。最后整代 `_assess_population()` 打分。

**输入 → 输出：** 50 个旧个体 → 50 个新个体 + 分数。

**为什么：** 精英保留保证不退步，锦标赛给好个体更多繁殖机会，自适应变异让前期探索、后期收敛，停滞重启避免整个种群卡在同一个局部好解。

### 第 9 步：收尾，把最优个体的第一步交出去

**在干什么：** 从「最好的那套下法」里取出**第一步**作为落子。

**函数具体做什么：** 循环结束后取 `move = self._best_move`；若它为空或不在当前合法步里（极端兜底），就取 `current_candidates(board)[0]` 或 `legal[0]`。写 `think.best_move`、按是否超时设 `note = "预算用尽，返回当前最优"` / `"搜索完成"`，`finish()` + `_emit()` + `return move`。

**输入 → 输出：** 全局最优个体 → 一个坐标 `(7, 8)`。

**为什么：** 我们推演了一整条 6 步序列，但真正只能落**第一步**；下一次轮到 AI 时会重新建种群。

> **一句话记住整条链：** 读预算 → 清空状态 → 预检 → 先验+随机造种群 → 整代 `decode()` + 批量打分 → 逐代 `_step()`（IGA：选父 / 交叉 / 变异 / 重启）→ `_publish()` 播报 → 返回 `_best_move`。
>
> 上面每一步的**真实源码片段与逐行解释**在第 5 节；图 1 就是这条链。

## 4. 名词速查

| 名词 | 大白话 | 在项目里的取值 / 位置 |
| --- | --- | --- |
| 个体 / 染色体 | 一张写着「接下来怎么下」的纸条 | 长度 `EVO_HORIZON = 6` 的 `[0,1)` 向量 |
| 种群 | 一批纸条 | `EVO_POPULATION = 50` |
| 解码 `decode()` | 把小数按**当前**合法步清单换算成落子 | `ai/evolution/kernel.py` 第 58 行 |
| 适应度 | 推演完末局面的分数 | `WIN_SCORE - steps` 或 `evaluate()` |
| 对手模型 | 简化版「对手会怎么应」 | `_heuristic_reply()`，前 `OPPONENT_TOP = 12` 个候选取贪心 |
| 先验种子 | 开局就把明显的好点塞进种群 | `prior_vectors()`，`SEED_TOP = 8` |
| 精英保留 | 最好的个体直接进下一代 | `EVO_ELITE = 2` |
| 停滞重启 | 连续多代没进步就随机换掉一批 | `EVO_STALL_LIMIT = 6` |
| 适应度缓存 | 相同个体不重复推演 | `_fitness_cache`，超 20000 条清空 |
| 预算 | 代数或时间，先到即停 | `EVO_GENERATIONS = 500` / `EVO_TIME_LIMIT = 20.0` |

## 5. 源码逐段精读

> **进阶提醒：** 建议按 `base.py → kernel.py → optimizers.py` 的顺序读，先骨架后细节。

![图 1　进化类公共管线 + IGA 一代：上排中文动作、下排代码定位](architecture/04_iga_flow.png)

**图 1　代码调用链**（可编辑 Visio 源：[04_iga_flow.vsdx](architecture/04_iga_flow.vsdx)）

![图 2　进化类公共架构：编码 / 推演 / 评估 / IGA 算子 / 输出](architecture/04_iga_arch.png)

**图 2　代码模块架构**（可编辑 Visio 源：[04_iga_arch.vsdx](architecture/04_iga_arch.vsdx)）

**怎么读这两张图：** 每个节点**上排是中文动作说明**，**下排才是文件与函数定位**。例如「整代解码并批量打分」下面写的是 `_assess_population() → kernel.decode() / batch_scores()`。先读上排理解流程，再看下排找源码。PNG 与 VSDX 文字完全一致。

### 5.1 基类构造与状态重置

**定位：`ai/evolution/base.py` 第 35—62 行（节选）**

```python
def __init__(self, player, config) -> None:
    super().__init__(player, config)
    # getattr 同时兼容主进程 Config 与多进程 worker 的 SimpleNamespace
    self.pop_size = max(4, int(getattr(config, "evo_population", 30)))
    self.generations = max(1, int(getattr(config, "evo_generations", 50)))
    self.horizon = max(1, int(getattr(config, "evo_horizon", 6)))
    self.time_limit = float(getattr(config, "evo_time", 8.0))
    self.rng = random.Random(getattr(config, "random_seed", None))
    self.timer = MoveTimer(self.time_limit)
    self._backend = backend_name()
    self._reset_search()

def _reset_search(self) -> None:
    self._evaluated = 0
    self._fitness_cache = {}
    self._best_score = VERY_BAD
    self._best_vec = None
    self._best_move = None
    self._move_scores = {}
    self._last_best = VERY_BAD
    self._stall = 0
    self._velocity = self._pbest = self._pbest_scores = self._trials = None
```

**逐行看懂：** `getattr` 的第二个数（30 / 50 / 6 / 8.0）只是**兜底**，真实默认在 `config/settings.py`（50 / 500 / 6 / 20.0）。`_reset_search()` 里最后一行把 PSO / ABC 的跨代状态一并清空——这四个字段放在基类，是因为四种算法共用同一个 `select_move()` 生命周期。

### 5.2 向量解码：连续小数怎么变成合法棋步

**定位：`ai/evolution/kernel.py` 第 58—96 行（节选）**

```python
def decode(board, vector, player, horizon):
    state = board.copy()
    first = None
    steps = 0
    for j in range(horizon):
        if state.game_over:
            break
        if state.current_player != player:
            if not state.has_legal_moves(player):
                break
            state.current_player = player
        cands = current_candidates(state)
        if not cands:
            break
        v = vector[j] if j < len(vector) else 0.5
        idx = int(v * len(cands))
        idx = max(0, min(len(cands) - 1, idx))
        move = cands[idx]
        if first is None:
            first = move
        if not _fast_apply(state, move):
            break
        steps += 1
        if state.game_over:
            break
        _heuristic_reply(state)
    return first, state, steps
```

**逐行看懂：**

1. 又是 `board.copy()`：推演绝不能改真实棋盘。
2. `cands = current_candidates(state)` **每一维都重新取**——所以同一个 `0.73` 在不同局面下对应完全不同的落点。这是初学者最容易误解的一点。
3. `idx = int(v * len(cands))` 把 `[0,1)` 的小数映射成候选清单下标，再用 `max/min` 夹住边界。因此交叉、变异产生的任意实数都能解码，**永远不会产生非法着法**。
4. 每落一步后 `_heuristic_reply(state)` 让对手应一手（一层贪心），再进入下一维；`first` 只记第一次的落点，它就是个体「主张」的正式落子。

### 5.3 适应度与先验种子

**定位：`kernel.py` 第 99—112、127—152 行（节选）**

```python
def fitness(board, vector, player, horizon):
    first, state, steps = decode(board, vector, player, horizon)
    if first is None:
        return VERY_BAD, None
    if state.game_over and state.winner:
        if state.winner == player:
            return WIN_SCORE - steps, first
        if state.winner == DRAW:
            return 0.0, first
        return -WIN_SCORE + steps, first
    return evaluate(state, player), first
```

```python
def prior_vectors(board, player, horizon, rng, count):
    cands = current_candidates(board)
    index = {m: i for i, m in enumerate(cands)}
    strong = []
    if type(board).__name__ == "GomokuBoard":
        strong += gomoku_attack_points(board, player)
        strong += gomoku_defense_points(board, player)
    strong += sort_moves_by_heuristic(board, cands, player)[:SEED_TOP]
    vectors = []
    for m in strong:
        v = [(index[m] + 0.5) / len(cands)]
        v += [rng.random() for _ in range(horizon - 1)]
        vectors.append(v)
    return vectors
```

**逐行看懂：** `WIN_SCORE - steps` 里的 `- steps` 表示「越快取胜越好」；`prior_vectors()` 用 `(索引 + 0.5)/候选数` 反推出「能让第一维选中这个好点」的小数，其余维度随机。这是把棋理先验塞进连续向量的巧妙做法。

### 5.4 公共入口 `select_move()`

**定位：`base.py` 第 161—214 行（节选）**

```python
def select_move(self, board, on_progress=None):
    self._begin_think()
    if type(board).__name__ == "ChessBoard":
        self.horizon = min(self.horizon, 3)
    elif type(board).__name__ == "GoBoard" and board.size >= 19:
        self.horizon = min(self.horizon, 4)
    self._reset_search()
    self.timer.start()

    legal = board.get_legal_moves()
    if not legal:
        ...
        return None
    forced, note = forced_move(board, self.player)
    if forced is not None:
        ...
        return forced

    pop = self._init_population(board)
    scores = self._assess_population(board, pop)
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
    ...
    return move
```

**逐行看懂：** 棋种自适应 `horizon`、预检、初始化、整代评估、主循环、兜底返回，六件事一目了然。`_step()` 是唯一由子类决定的部分（基类第 216 行直接 `raise NotImplementedError`）。

### 5.5 IGA 的一代算子

**定位：`optimizers.py` 第 29—60 行（节选）**

```python
def __init__(self, player, config):
    super().__init__(player, config)
    self.elite = max(1, int(getattr(config, "evo_elite", 2)))
    self.stall_limit = max(2, int(getattr(config, "evo_stall_limit", 6)))
    self.base_mutation = 0.35

def _tournament(self, pop, scores):
    k = min(3, len(pop))
    best = max(self.rng.sample(range(len(pop)), k), key=lambda i: scores[i])
    return pop[best]

def _step(self, pop, scores, board, gen):
    order = sorted(range(n), key=lambda i: -scores[i])
    mutation = self.base_mutation * (1.0 - 0.8 * gen / max(1, self.generations))
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
```

**逐行看懂：** `mutation` 从 0.35 线性降到约 0.07（前期大改、后期细调）；`keep` 在停滞时从 2 降到 1，配合「其余全部重新随机生成」实现重启；交叉是逐维抛硬币；变异后 `% 1.0` 保证分量仍在 `[0,1)`。

### 5.6 本节小结：把函数名串起来

```
ai/evolution/base.py · EvolutionaryAI.select_move()
  ├─ _reset_search() / timer.start()
  ├─ kernel.forced_move() → ai/candidates.py · gomoku_forced_move()
  ├─ _init_population() → kernel.prior_vectors() + _random_vector()
  ├─ _assess_population()
  │    ├─ kernel.decode() → current_candidates() / _heuristic_reply()
  │    ├─ ai/accel/batch.py · batch_scores()（numpy / 可选 CUDA）
  │    └─ _record() → _move_scores / _best_move
  ├─ for gen in 1..EVO_GENERATIONS:
  │    ├─ optimizers.py · ImprovedGeneticAI._step()
  │    │    → _tournament() / 均匀交叉 / 高斯变异 / 停滞重启
  │    └─ _publish(gen) → _emit() → ThinkState
  └─ return _best_move → (row, col)
```

| 常量 / 字段 | 定义处 | 含义 |
| --- | --- | --- |
| `WIN_SCORE` / `VERY_BAD` | `kernel.py` 第 22—23 行 | `1e6` / `-1e18` |
| `OPPONENT_TOP` / `SEED_TOP` | 第 24—25 行 | 12 / 8 |
| `EVO_POPULATION` / `EVO_GENERATIONS` | `config/settings.py` | 50 / 500 |
| `EVO_HORIZON` / `EVO_TIME_LIMIT` | 同上 | 6 / 20.0 秒 |
| `EVO_ELITE` / `EVO_STALL_LIMIT` | 同上 | 2 / 6 |
| `base_mutation` | `optimizers.py` 第 33 行 | 0.35，随代数递减 |

## 6. 代码模块地图

| 文件 | 类 / 函数 | 作用 | 被谁调用 | 建议读码顺序 |
| --- | --- | --- | --- | --- |
| `ai/evolution/base.py` | `EvolutionaryAI.__init__()` / `_reset_search()` | 读预算、清状态 | `create_ai()` | ① |
| `ai/evolution/base.py` | `select_move()` | 四种算法共用的主流程 | `step_ai()` | ② |
| `ai/evolution/kernel.py` | `decode()` / `fitness()` / `_heuristic_reply()` | 向量解码、对手模型、适应度 | `_assess_population()` | ③ |
| `ai/evolution/kernel.py` | `prior_vectors()` / `forced_move()` / `current_candidates()` | 先验种子、预检、候选 | `_init_population()` | ④ |
| `ai/evolution/base.py` | `_assess_population()` / `_assess()` / `_record()` | 整代评估、缓存、全局最优 | `select_move()`、`_step()` | ⑤ |
| `ai/accel/batch.py` | `batch_scores()` | numpy / CUDA 批量局面打分 | `_assess_population()` | ⑥ |
| `ai/evolution/optimizers.py` | `ImprovedGeneticAI._step()` / `_tournament()` | IGA 一代算子 | 主循环 | ⑦ |
| `ai/evolution/base.py` | `_publish()` / `_top_moves()` | 写 `ThinkState`、算停滞 | 每代末尾 | ⑧ |
| `ai/candidates.py` | `candidate_moves()` / `gomoku_forced_move()` | 候选裁剪与公共预检 | `kernel.py` | ⑨ |
| `ai/evaluator.py` | `evaluate()` | 末局面打分 | `fitness()` | ⑩ |
| `config/settings.py` | `EVO_*` 系列 | 四种算法共用的预算 | `load_config()` | ⑪ |

**推荐读码路线：** ② `select_move()` → ③ `decode()`（本篇最核心）→ ⑤ `_assess_population()` → ⑦ 任意一个子类的 `_step()`。读完这四个，05—07 三篇就只是在对比四种不同的 `_step()`。

## 7. 动手试一试

```bash
# IGA 对随机基线：确认「进化确实比瞎下强」
python start.py --game gomoku --mode ai_vs_ai --p1-ai iga --p2-ai random --seed 42

# 把预算收紧到 20 代 / 2 秒，观察棋力明显下降
python start.py --game gomoku --mode ai_vs_ai --p1-ai iga --p2-ai random --evo-generations 20 --evo-time 2 --seed 42

# 四种进化算法横向 PK（它们共用同一组 EVO_* 预算）
python start.py --game othello --mode ai_vs_ai --p1-ai iga --p2-ai de --evo-time 5 --seed 42
```

| 参数 | 默认值 | 调大之后会看到什么 |
| --- | --- | --- |
| `--evo-population` | 50 | 种群更丰富、不易早熟，但每代更慢 |
| `--evo-generations` | 500 | 迭代更多轮，通常与 `--evo-time` 同时起作用 |
| `--evo-horizon` | 6 | 推演看得更远，但向量维度变大、搜索更难 |
| `--evo-time` | 20.0 秒 | 与代数构成双预算，先到即停 |

> **初学者提示：** 参数默认值以 `config/settings.py` 为准；`base.py` 里 `getattr` 的第二个数只是配置缺字段时的兜底，别被它误导。四种进化算法共用同一组预算，所以横向 PK 是公平的。

## 8. 常见疑问与已知限制

**问：为什么不直接对棋盘坐标做交叉变异？**

答：两个合法坐标交叉后很可能是非法位置。改用「候选清单索引 + 解码」，连续算子就能原样复用，且天然满足合法性（见 5.2）。

**问：对手模型只有一层贪心，会不会太天真？**

答：会。`_heuristic_reply()` 只在前 12 个候选里挑棋理分最高的一手，不代表对手的最优应对，这正是进化类算法棋力不如树搜索的主要原因之一。

**问：`getattr(config, "evo_population", 30)` 里的 30 是默认值吗？**

答：**不是**。那是 `Config` 缺字段时的兜底；正常运行时 `load_config()` 会提供 `evo_population = 50`（来自 `settings.py`）。这类「兜底值与实际值不一致」是读源码时容易踩的坑。

**问：向量的每一维对应固定坐标吗？**

答：不对应。`decode()` 每推演一步都重新调 `current_candidates(state)`，所以同一个小数在不同局面下是不同的一步。

**问：这四种算法为什么棋力偏弱？**

答：它们是无模型采样，没有完备的「我最优 / 你最优」对抗推演。在本项目里定位是算法 PK 横向对照与教学演示。

- 已知限制：适应度中的对手模型只有一层贪心近似。
- 已知限制：战术底线依赖公共强制预检，种群本身不保证抓住必胜点。
- 已知限制：不做跨回合复用，每步重建整个种群。
- 适合场景：连续参数离线寻优（例如调优评估函数权重）才是这类算法真正擅长的，见第 05 篇。
- 文档定位：代码片段是节选，完整实现以 `ai/evolution/` 下三个文件为准。

---

*ACBP 棋类综合对战平台 · 算法学习文档 · 第 04 篇 / 共 10 篇 · 代码片段基于 2026-11-10 源码*
