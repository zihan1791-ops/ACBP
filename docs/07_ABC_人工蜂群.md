# 07　ABC：把候选解当成一片片花圃

> 雇佣蜂 / 跟随蜂 / 侦察蜂三阶段，逐行读 `ArtificialBeeColonyAI._step()`

**编号 07　|　难度：进阶　|　建议阅读：22 分钟　|　前置：第 04 篇（进化类公共底座）**

[← 返回文档导航](README.md)　|　上一篇：[06 PSO 粒子群优化](06_PSO_粒子群优化.md)　|　下一篇：[08 Edax 黑白棋专用引擎](08_Edax_黑白棋专用引擎.md)

> **30 秒速览：** ABC 用三种角色分工：雇佣蜂守着一片花圃（候选解）在附近试新位置，跟随蜂按花蜜多少决定去帮谁的忙，侦察蜂把长期没有收成的花圃直接换掉。探索与开采靠这套分工自然平衡。公共管线完全沿用第 04 篇，这一篇把 ABC 的 `_step()` 与 `_perturb()` 逐行读完。

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

一句话：ABC 是「有分工的邻域搜索」，好解被反复开采、差解被定期重置。

读完你应该能回答：

- 三种蜂各自做什么，为什么需要三种？
- `trial` 计数是什么，达到阈值后为什么必须整片换掉？
- 「邻域扰动」在棋步向量上具体改了什么？

**这一篇会带你读的文件：** `ai/evolution/optimizers.py`（ABC 部分）、`ai/evolution/base.py`（`_assess()` / `_random_vector()` / `_reset_search()`）、`ai/evolution/kernel.py`（`decode()`）、`config/settings.py`。公共管线见第 04 篇。

## 2. 先用直觉理解

把每个候选解想成一片花圃。雇佣蜂一人守一片，只在自家附近换个角度试试有没有更甜的花；跟随蜂不固定守哪片，而是看哪片花蜜多就多派几只去帮着找；侦察蜂专门处理「连续好多天一点没长进」的花圃——与其继续耗着，不如整片翻掉重新播随机种子。

于是好解被集中开采（ exploitation ），长期没希望的解被强制换掉（ exploration ），这两件事由不同角色负责，互不干扰。

> **初学者提示：** 和 PSO 的区别：PSO 靠「向全群最优靠拢」收敛，ABC 靠「按适应度比例分配搜索次数」收敛，并且有明确的**放弃机制**来保住多样性。

## 3. 跟着代码走一遍

> **这一节是整篇最关键的部分。** 设 50 个食物源、向量长度 6、`EVO_ABC_LIMIT = 5`（连续 5 代没改进就放弃）。下面按 `ArtificialBeeColonyAI._step()` 的真实顺序走 7 步。

### 先收好这张「函数名对照表」

| 函数名（英文） | 中文作用（它到底干了什么） | 输入 → 输出 |
| --- | --- | --- |
| `ArtificialBeeColonyAI._step()` | ABC 的一代：雇佣蜂 → 跟随蜂 → 侦察蜂 | 种群 + 分数 → 新种群 + 新分数 |
| `_perturb()` | 邻域扰动：随机挑一维，参照另一个个体改一改 | 种群 + 下标 → 新向量 |
| `_trials` | 每个食物源「连续多少代没进步」的计数 | 50 个整数 |
| `_assess()` | 评估单个个体（带适应度缓存），并更新全局最优 | 向量 → 分数 |
| `_random_vector()` | 造一个全新的随机个体（侦察蜂用） | 无 → 长度 6 的 `[0,1)` 向量 |
| `weights` / `acc` | 轮盘赌：按适应度比例挑选要开采的食物源 | 分数列表 → 被选中的下标 |
| `VERY_BAD` | 无效 / 超时个体的极低分 | `-1e18` |
| `kernel.decode()` | 把向量翻译成合法推演序列（第 04 篇 5.2） | 向量 → 首步 / 末局面 / 步数 |
| `_reset_search()` | 每步选棋开头把 `_trials` 等状态清空 | 无 → 状态归零 |

### 第 1 步：进入一代，初始化停滞计数

**在干什么：** 给每个食物源准备一个「多久没长进」的计数器。

**函数具体做什么：** `if self._trials is None: self._trials = [0] * n`。`_trials` 定义在基类 `_reset_search()` 里（初值 `None`），所以每次 `select_move()` 开头会被清空，只在**一次落子的多代之间**保留。构造函数里 `self.limit = max(2, int(getattr(config, "evo_abc_limit", 5)))`，实际值来自 `config/settings.py` 的 `EVO_ABC_LIMIT = 5`。

**输入 → 输出：** `n = 50` → `_trials = [0, 0, ..., 0]`；`limit = 5`。

**为什么：** 后面侦察蜂要靠它判断「哪片花圃该放弃」。

### 第 2 步：雇佣蜂——每个食物源就近试一次

**在干什么：** 给每片花圃一次「在附近找更甜的花」的机会。

**函数具体做什么：** `for i in range(n):` 每轮先 `if self.timer.timeout: break`；然后 `cand = self._perturb(pop, i)` 造一个邻域新解，`fs = self._assess(board, cand)` 打分。若 `fs > scores[i]` 就**原地替换** `pop[i], scores[i]` 并把 `_trials[i] = 0`；否则只把 `_trials[i] += 1`。

**输入 → 输出：** 50 个旧食物源 → 若干被改进、其余停滞计数 +1。

**为什么：** 「只有更优才替换」的贪婪选择保证种群质量单调不降；每代每个源至少试一次，是最基本的开采。

### 第 3 步：`_perturb()` 到底改了什么

**在干什么：** 生成「附近」的新解，而不是完全随机重来。

**函数具体做什么：** 复制一份 `pop[i]`；随机选一维 `d = rng.randrange(horizon)`、随机选另一个个体 `k = rng.randrange(len(pop))`、抽一个 `phi = rng.uniform(-1.0, 1.0)`；然后 `v[d] = (v[d] + phi * (v[d] - pop[k][d])) % 1.0`。也就是**只改一维**，改变量是「自己和另一个个体在该维的差」乘以一个 ±1 的随机系数。

**输入 → 输出：** `[0.12, 0.73, 0.40, ...]` → 例如只把第 2 维改成 `0.61`，其余不变。

**为什么：** 只动一维相当于「改变推演序列里某一步的选择」，是离散棋步空间里最自然的邻域定义；`% 1.0` 保证仍可解码。

### 第 4 步：跟随蜂——按花蜜多少分配搜索次数

**在干什么：** 把更多计算预算押在优质食物源上。

**函数具体做什么：** 先把 `VERY_BAD` 的无效分数排除，`base = min(valid)`，再算 `weights = [(s - base + 1.0) if s > VERY_BAD else 0.0 for s in scores]`。这里先**平移到非负**再加 1，是为了让最低分也有一点点被选中的机会，同时避免负分破坏轮盘赌。随后 `total = sum(weights)`，循环 n 次：抽 `r = rng.random() * total`，用 `acc` 累加 `weights` 找到第一个 `acc >= r` 的下标 `pick`（经典轮盘赌）。

**输入 → 输出：** 50 个分数 → n 次抽样，分数越高被选中次数越多。

**为什么：** 优质花圃在一代里可能被扰动多次，等效于「把搜索预算集中在更有希望的区域」。

### 第 5 步：跟随蜂再扰动一次，仍是贪婪替换

**在干什么：** 对被选中的食物源再做一次邻域试探。

**函数具体做什么：** `cand = self._perturb(pop, pick)`、`fs = self._assess(board, cand)`；`if fs > scores[pick]:` 替换并把 `_trials[pick] = 0`，否则 `_trials[pick] += 1`。逻辑与雇佣蜂完全一样，只是**选谁**由轮盘赌决定。

**输入 → 输出：** 被选中的若干食物源 → 可能改进、可能停滞 +1。

**为什么：** 与雇佣蜂共用同一套贪婪选择，保证「种群质量单调不降」这条性质不被破坏。

### 第 6 步：侦察蜂——停滞太久就整片换掉

**在干什么：** 处理「连续好多代一点没长进」的花圃。

**函数具体做什么：** `for i in range(n): if self._trials[i] >= self.limit:` 就 `pop[i] = self._random_vector()`（一个全新的随机向量）、`scores[i] = self._assess(board, pop[i])` 重新打分、`_trials[i] = 0` 计数归零。

**输入 → 输出：** 停滞 5 代的食物源 → 全新随机个体，计数清零。

**为什么：** `trial` 给每个解单独记「多久没进步」，粒度比「全局判断收敛」更细，不容易误伤还在缓慢爬坡的解；同时强制注入多样性，避免全群困在同一个局部最优。

### 第 7 步：返回新种群，交回公共管线

**在干什么：** 一代结束。

**函数具体做什么：** `return pop, scores`（注意 ABC 是**原地修改** `pop` 和 `scores` 后返回同一个列表对象，与 DE / PSO 构造新列表不同）。基类接着 `_publish(gen)` 写 `ThinkState`、`_emit()` 推给界面；整轮结束返回 `_best_move`（第 04 篇 5.4）。下一次 `select_move()` 会清空 `_trials`。

**输入 → 输出：** 50 个食物源 → 公共管线的下一轮。

**为什么：** 三种蜂只负责「怎么改种群」，预算、可视化、返回落子仍由基类统一处理。

> **一句话记住整条链：** 初始化 `_trials` → 雇佣蜂逐源扰动 + 贪婪替换 → 跟随蜂按适应度轮盘赌再扰动 → 侦察蜂把停滞 ≥5 代的源整片随机重置 → 返回种群。
>
> 上面每一步的**真实源码片段与逐行解释**在第 5 节；图 1 就是这条链。

## 4. 名词速查

| 名词 | 大白话 | 在项目里的取值 / 位置 |
| --- | --- | --- |
| 食物源 | 一个候选解（= 一个向量） | 数量 = `EVO_POPULATION = 50` |
| 雇佣蜂 | 一蜂守一片，在附近试新解 | 每片花圃各一次 `_perturb()` |
| 跟随蜂 | 按花蜜多少挑花圃帮忙 | 轮盘赌 `weights` / `acc` |
| 侦察蜂 | 放弃久无改进的花圃，随机重置 | `_trials[i] >= limit` |
| `trial` | 连续多少代没进步 | 改进即归零 |
| `limit` | 放弃阈值 | `EVO_ABC_LIMIT = 5` |
| 轮盘赌 | 越好的解被选中概率越高 | 先平移到非负再加权 |
| 贪婪选择 | 只有更优才替换 | 种群质量单调不降 |
| 邻域扰动 | 只改向量中某一维 | `_perturb()` |
| 模 1 回绕 | 折回 `[0,1)` | `% 1.0` |

## 5. 源码逐段精读

> **进阶提醒：** 公共管线见第 04 篇；这一节只读 ABC 自己的 55 行。

![图 1　ABC 一代的代码调用链：上排中文动作、下排代码定位](architecture/07_abc_flow.png)

**图 1　代码调用链**（可编辑 Visio 源：[07_abc_flow.vsdx](architecture/07_abc_flow.vsdx)）

![图 2　ABC 代码模块架构：食物源 / 三种蜂 / 扰动评估 / 输出](architecture/07_abc_arch.png)

**图 2　代码模块架构**（可编辑 Visio 源：[07_abc_arch.vsdx](architecture/07_abc_arch.vsdx)）

**怎么读这两张图：** 每个节点**上排是中文动作说明**，**下排才是文件与函数定位**。例如「跟随蜂：按适应度轮盘赌挑食物源」下面写的是 `weights / acc >= r`。先读上排理解流程，再看下排找源码。PNG 与 VSDX 文字完全一致。

### 5.1 构造、邻域扰动与完整的 `_step()`

**定位：`ai/evolution/optimizers.py` 第 153—210 行（节选）**

```python
def __init__(self, player, config):
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
```

**逐行看懂：**

1. `_perturb()` 只改**一维**：`d` 随机、`k` 随机参照个体、`phi ∈ [-1,1]`；这是「邻域」的具体定义。
2. 轮盘赌的 `weights` 先减 `base` 再加 1.0，保证非负且最低分也有微小机会；`if total > 0` 防止全为 0 时除零。
3. 三处都检查 `timer.timeout`，20 秒预算是硬约束。
4. 侦察蜂段**不检查超时**（它只是随机重置 + 一次评估，开销小且必须完成，否则 `_trials` 会一直累积）。
5. ABC 原地修改 `pop` / `scores` 并返回它们，与 DE / PSO 构造新列表不同——读这四种 `_step()` 时留意返回值的形态差异。

### 5.2 单个评估与全局最优

**定位：`ai/evolution/base.py` 第 64—77、114—123 行（节选）**

```python
def _assess(self, board, vector) -> float:
    if self.timer.timeout:
        return VERY_BAD
    key = tuple(round(float(x), 7) for x in vector)
    cached = self._fitness_cache.get(key)
    if cached is None:
        score, first = fitness(board, vector, self.player, self.horizon)
        self._fitness_cache[key] = (score, first)
    else:
        score, first = cached
    return self._record(vector, score, first)

def _record(self, vector, score, first) -> float:
    self._evaluated += 1
    if first is not None:
        if score > self._move_scores.get(first, VERY_BAD):
            self._move_scores[first] = score
        if score > self._best_score:
            self._best_score = score
            self._best_vec = list(vector)
            self._best_move = first
    return score
```

**逐行看懂：** 每次 `_assess()` 都会顺手更新 `_move_scores`（每个首步的最好分）和 `_best_move`（全局最优个体的第一步）。所以 ABC 虽然只在「食物源」层面做替换，最终落子依然来自全局最优，不会退化成「随便挑一片花圃」。

### 5.3 本节小结：把函数名串起来

```
ai/evolution/base.py · EvolutionaryAI.select_move()   （第 04 篇）
  └─ for gen in 1..EVO_GENERATIONS:
     └─ ai/evolution/optimizers.py · ArtificialBeeColonyAI._step()
        ├─ _trials = [0] * n（首次）
        ├─ 雇佣蜂：for i → _perturb(pop, i) → _assess() → 贪婪替换 / trial+1
        ├─ 跟随蜂：weights 平移 → 轮盘赌 pick → _perturb() → 贪婪替换
        ├─ 侦察蜂：_trials[i] >= limit → _random_vector() → _assess() → trial=0
        └─ 返回（原地修改过的）pop, scores
```

| 常量 / 字段 | 定义处 | 含义 |
| --- | --- | --- |
| `self.limit` | `optimizers.py` 第 155 行 | 5，连续未改进多少代放弃 |
| `_trials` | `base.py · _reset_search()` | 每步选棋开头清空 |
| `phi` | `_perturb()` 内 | `[-1, 1]` 随机数 |
| `VERY_BAD` | `kernel.py` 第 23 行 | `-1e18` |
| `base` / `total` | `_step()` 内 | 轮盘赌权重平移与总和 |

## 6. 代码模块地图

| 文件 | 类 / 函数 | 作用 | 被谁调用 | 建议读码顺序 |
| --- | --- | --- | --- | --- |
| `ai/evolution/optimizers.py` | `ArtificialBeeColonyAI.__init__()` | 读放弃阈值 | `create_ai()` | ① |
| `ai/evolution/optimizers.py` | `_perturb()` | 邻域扰动（只改一维） | `_step()` | ② |
| `ai/evolution/optimizers.py` | `_step()` | **三阶段一代算子** | 基类主循环 | ③ |
| `ai/evolution/base.py` | `_assess()` / `_record()` | 单个体评估、更新全局最优 | `_step()` | ④ |
| `ai/evolution/base.py` | `_random_vector()` / `_reset_search()` | 侦察蜂随机重置、清状态 | `_step()` / `select_move()` | ⑤ |
| `ai/evolution/kernel.py` | `decode()` / `fitness()` | 向量解码与适应度 | `_assess()` | ⑥ |
| `ai/evolution/base.py` | `_publish()` / `_top_moves()` | 播报进度与 Top3 | 每代末尾 | ⑦ |
| `config/settings.py` | `EVO_ABC_LIMIT` | 默认 5 | `load_config()` | ⑧ |

**推荐读码路线：** 第 04 篇 `select_move()` + `decode()` → 本篇 ② `_perturb()`（理解「邻域」是什么）→ ③ `_step()` 三段依次读 → ④ `_assess()`（理解为什么最终落子来自全局最优）。

## 7. 动手试一试

```bash
# ABC 对随机基线
python start.py --game gomoku --mode ai_vs_ai --p1-ai abc --p2-ai random --seed 42

# 与 PSO 横向对比（一个靠放弃、一个靠牵引）
python start.py --game othello --mode ai_vs_ai --p1-ai abc --p2-ai pso --evo-time 5 --seed 42

# 代数收紧，观察「侦察蜂还没来得及起作用」
python start.py --game gomoku --mode ai_vs_ai --p1-ai abc --p2-ai random --evo-generations 10 --evo-time 2 --seed 42
```

| 参数 | 默认值 | 怎么调 / 会看到什么 |
| --- | --- | --- |
| `EVO_ABC_LIMIT`（源码） | 5 | 调小更频繁重置（更探索），调大更耐心开采 |
| `--evo-population` | 50 | 花圃数量，同时也是雇佣蜂数量 |
| `--evo-generations` | 500 | 代数太少时侦察蜂几乎不触发 |
| `--evo-time` | 20.0 秒 | 与代数构成双预算，先到即停 |

> **初学者提示：** `EVO_ABC_LIMIT` 在 `config/settings.py` 里，改完重启程序生效。想看侦察蜂是否起作用，把代数压到 10（此时 `trial` 很难累到 5），再和默认 500 代对比。

## 8. 常见疑问与已知限制

**问：ABC 为什么常比 GA / DE 评估次数多？**

答：一代里雇佣蜂和跟随蜂各做 n 次扰动，优质花圃还会被轮盘赌重复选中，总评估次数自然更高；`_fitness_cache` 能免掉重复个体的推演，但省不掉全部。

**问：把 `limit` 调大一点会怎样？**

答：解被保留得更久、开采更充分，但更容易困在局部最优；多峰适应度地形（如中残局）下通常反而需要一个**偏小**的阈值。

**问：轮盘赌为什么要先减 `base` 再加 1？**

答：见 5.1。适应度可能是负数（输棋给 `-WIN_SCORE + steps`），直接当权重会破坏概率；平移到非负再 +1，既解决负分，也让最低分保留一点被选中的机会。

**问：它的棋力比树搜索弱吗？**

答：是的。和另外三种进化算法一样，没有对手最优应对的完备性，定位为算法 PK 对照基线。

- 已知限制：评估次数通常多于 GA / DE，单步耗时略高。
- 已知限制：对手模型只有一层贪心（第 04 篇）。
- 已知限制：三种蜂阶段都靠 `_assess()` 逐个评估，没有整代批量打分路径。
- 相对优势：侦察蜂带来的多样性在多峰适应度地形（中残局）下更稳。
- 文档定位：代码片段是节选，完整实现以 `ai/evolution/optimizers.py` 为准。

---

*ACBP 棋类综合对战平台 · 算法学习文档 · 第 07 篇 / 共 10 篇 · 代码片段基于 2026-11-10 源码*
