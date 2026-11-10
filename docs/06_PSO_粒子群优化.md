# 06　PSO：一群粒子一起向「历史最好」靠

> 惯性 + 个体经验 + 群体经验，逐行读 `ParticleSwarmAI._step()`

**编号 06　|　难度：进阶　|　建议阅读：22 分钟　|　前置：第 04 篇（进化类公共底座）**

[← 返回文档导航](README.md)　|　上一篇：[05 DE 差分进化](05_DE_差分进化算法.md)　|　下一篇：[07 ABC 人工蜂群](07_ABC_人工蜂群.md)

> **30 秒速览：** 每个粒子都记得「自己这辈子到过的最好位置」，也知道「全群目前的最好位置」。每一代，它带着惯性、被这两个位置同时拉一把，于是早期满场探索、后期集中收敛。公共管线完全沿用第 04 篇，这一篇只把 PSO 的 `_step()` 与三个跨代状态逐行读完。

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

一句话：PSO 让一群候选解像鸟群一样飞行，靠「个体经验 + 群体经验」而不是交叉变异来改进。

读完你应该能回答：

- 速度 `v` 在这个算法里到底代表什么，为什么要保留上一代的速度？
- `pbest` 和 `gbest` 分别是什么、由谁更新？
- 为什么每次重新选步时，这些跨代状态都要清空？

**这一篇会带你读的文件：** `ai/evolution/optimizers.py`（PSO 部分）、`ai/evolution/base.py`（`_reset_search()` / `_assess_population()`）、`ai/evolution/kernel.py`（`decode()`）、`config/settings.py`。公共管线见第 04 篇。

## 2. 先用直觉理解

鸟群找食物时，每只鸟不知道食物在哪，但知道两件事：「我自己飞过的最香的位置」和「大家目前发现的最香的位置」。于是它一边保持原来的飞行惯性，一边朝这两个方向各偏一点。

惯性权重 `w` 随代数递减：早期 `w` 大，飞得野、覆盖面广；后期 `w` 小，大家慢慢收拢到最有希望的区域细找。这就是「惯性递减全局版 PSO」。

> **初学者提示：** 和 DE 一样，粒子位置仍是长度 6 的 `[0,1)` 实数向量，解码成棋步的整套机制完全沿用第 04 篇。PSO 多出来的，是**跨代记忆**。

## 3. 跟着代码走一遍

> **这一节是整篇最关键的部分。** 设 50 个粒子、向量长度 6、`EVO_GENERATIONS = 500`。下面按 `ParticleSwarmAI._step()` 的真实顺序走 7 步。

### 先收好这张「函数名对照表」

| 函数名（英文） | 中文作用（它到底干了什么） | 输入 → 输出 |
| --- | --- | --- |
| `ParticleSwarmAI._step()` | PSO 的一代：更新速度 → 更新位置 → 整代评估 → 更新个体最优 | 种群 + 分数 → 新种群 + 新分数 |
| `_velocity` | 每个粒子上一代的速度向量（跨代保留） | 50 个 6 维向量 |
| `_pbest` / `_pbest_scores` | 每个粒子自己历史上最好的位置与分数 | 50 个向量 + 50 个分数 |
| `gbest` | 全群历史最优位置（本代从 `_pbest` 里挑出来） | 一个 6 维向量 |
| `_reset_search()` | 每步选棋开头把上面三个状态全部清空 | 无 → 状态归零 |
| `_assess_population()` | 整代解码 + 批量打分（第 04 篇 5.4） | 种群 → 分数列表 |
| `kernel.decode()` | 把位置向量翻译成合法推演序列 | 向量 → 首步 / 末局面 / 步数 |
| `% 1.0` | 位置越界后按模 1 折回 `[0,1)` | 实数 → `[0,1)` 实数 |
| `max(-0.3, min(0.3, v))` | 速度限幅，防止一步飞太远 | 速度 → ±0.3 以内 |
| `_publish()` | 把代数、后端、最优步写进 `ThinkState` | 代数 → 界面状态 |

### 第 1 步：进入 PSO 的一代，先判断是不是第一次

**在干什么：** 第一次进 `_step()` 时，粒子还没有「速度」和「历史最优」，要先初始化。

**函数具体做什么：** `if self._velocity is None:` 时，给每个粒子造一个 6 维速度，每维取 `rng.uniform(-0.1, 0.1)`（很小的随机初始速度）；`self._pbest = [list(v) for v in pop]` 把当前位置当作各自的「历史最优」，`self._pbest_scores = list(scores)` 存对应分数。这三个字段都定义在基类 `_reset_search()` 里，初值为 `None`。

**输入 → 输出：** 50 个初始粒子 → 50 个速度向量 + 50 个 `pbest` + 50 个分数。

**为什么：** 速度是「上一次往哪飞」的记忆，第一代没有上一代，只能给个小随机值起步。

### 第 2 步：算这一代的惯性权重

**在干什么：** 决定「这一代更该探索，还是更该收敛」。

**函数具体做什么：** `w = 0.9 - 0.5 * min(1.0, gen / max(1, self.generations))`。`gen` 从 1 到 500，所以 `w` 从约 0.9 线性降到 0.4；`min(1.0, ...)` 防止代数超出上限后继续降。`max(1, self.generations)` 防除零。

**输入 → 输出：** `gen = 1` → `w ≈ 0.899`；`gen = 500` → `w = 0.4`。

**为什么：** 早期大惯性让粒子飞得远、覆盖更多区域；后期小惯性让大家在好区域附近细调。

### 第 3 步：找出全群历史最优 `gbest`

**在干什么：** 确定「大家目前发现的最香的位置」。

**函数具体做什么：** `g = max(range(n), key=lambda i: self._pbest_scores[i])` 找出**个体历史最优分数最高**的那个粒子下标，`gbest = self._pbest[g]` 取它的位置。注意用的是 `_pbest_scores`（各自历史最好），不是 `scores`（本代分数）。

**输入 → 输出：** 50 个 `_pbest_scores` → 一个下标 `g` 和一个 6 维向量 `gbest`。

**为什么：** 用历史最优而不是本代最优，可以避免某代偶然的好分数把全群带偏。

### 第 4 步：逐维更新速度——三项各管一件事

**在干什么：** 算出每个粒子这一代打算往哪飞、飞多快。

**函数具体做什么：** 对每一维 `d`，先抽两个随机数 `r1, r2`，再算：

```
v = w * vel[d]
    + 1.6 * r1 * (_pbest[i][d] - pos[d])     # 认知项：向自己的最好位置靠
    + 1.6 * r2 * (gbest[d] - pos[d])         # 社会项：向全群最好位置靠
```

`1.6` 是认知 / 社会系数（源码里直接写死的常数，不是配置项）。`r1, r2` 每次重新抽，让同样的两点之间也能飞出不同路线，保留随机性。

**输入 → 输出：** 旧速度 + 当前位置 + `pbest` + `gbest` → 一个新速度。

**为什么：** 三项分别是「保持惯性」「信自己」「信大家」；缺了惯性会抖，缺了认知项会全员挤到一个点，缺了社会项则各走各的、收敛很慢。

### 第 5 步：速度限幅 + 位置按模 1 回绕

**在干什么：** 把新速度夹在合理范围，再算出新位置。

**函数具体做什么：** `v = max(-0.3, min(0.3, v))` 把速度限制在 ±0.3；`nx.append((pos[d] + v) % 1.0)` 让位置始终落在 `[0,1)`。随后 `self._velocity[i] = nv` 把新速度存回跨代状态，`new_pop.append(nx)` 收集新位置。**速度本身不回绕**，只有位置回绕。

**输入 → 输出：** 速度 + 位置 → 50 个新位置向量，全部分量在 `[0,1)`。

**为什么：** 限幅防止「一步飞过整个搜索空间」；回绕保证 `decode()` 里 `int(v * len(cands))` 永远落在合法下标范围，不会产生非法着法。

### 第 6 步：整代评估并更新个体历史最优

**在干什么：** 给新位置打分，并把「我自己见过的最好位置」刷新。

**函数具体做什么：** `new_scores = self._assess_population(board, new_pop)` 一次解码整代、用 numpy / 可选 CUDA 批量打分（第 04 篇 5.4）。然后 `for i, s in enumerate(new_scores): if s > self._pbest_scores[i]:` 就更新 `_pbest_scores[i] = s`、`_pbest[i] = list(new_pop[i])`。注意 `gbest` 本代**不在这里更新**，要等下一代第 3 步重新从 `_pbest_scores` 里挑。

**输入 → 输出：** 50 个新位置 → 50 个分数 + 刷新后的 `_pbest` / `_pbest_scores`。

**为什么：** 个体最优是「只和自己的历史比」，与 DE 的「只和自己的原版本比」思路相近，但记忆跨度是整轮搜索而不是一代。

### 第 7 步：返回新种群，并注意跨代状态的生命周期

**在干什么：** 一代结束，交回公共管线；同时记住这些状态什么时候会被清掉。

**函数具体做什么：** `return new_pop, new_scores`。基类接着 `_publish(gen)` + `_emit()`。**关键**：下一次 `select_move()` 开头会调 `_reset_search()`，把 `_velocity / _pbest / _pbest_scores`（以及 ABC 用的 `_trials`）全部置回 `None`。原因是不同棋局的合法步清单完全不同，上一局的速度和最优向量在这一局没有任何意义。

**输入 → 输出：** 新种群 → 公共管线；下一局重新开始。

**为什么：** 这是「跨代」但**不跨回合**——很多 PSO 实现会犯「速度沿用整场对局」的错，本项目明确避免了。

> **一句话记住整条链：** 首次初始化速度/最优 → `w` 线性递减 → 找 `gbest` → 逐维算 `w*v + 认知项 + 社会项` → 限幅 ±0.3、位置 `% 1.0` → 整代打分 → 刷新 `_pbest`。
>
> 上面每一步的**真实源码片段与逐行解释**在第 5 节；图 1 就是这条链。

## 4. 名词速查

| 名词 | 大白话 | 在项目里的取值 / 位置 |
| --- | --- | --- |
| 粒子 particle | 一个候选解（= 一个向量） | `EVO_POPULATION = 50` |
| 速度 `v` | 这一代打算往哪个方向、挪多大 | `_velocity`，跨代保留 |
| 惯性 `w` | 保留多少上代速度 | `0.9 → 0.4` 线性递减 |
| `pbest` | 这个粒子自己见过的最好位置 | `_pbest` / `_pbest_scores` |
| `gbest` | 全群历史最好位置 | 本代从 `_pbest_scores` 取 `max` |
| 认知 / 社会系数 | 信自己 / 信大家的权重 | 源码常量 `1.6` |
| 速度限幅 | 一步最多飞多远 | `max(-0.3, min(0.3, v))` |
| 模 1 回绕 | 位置越界后折回 `[0,1)` | 速度不回绕 |
| `_reset_search()` | 每次选步前清空跨代状态 | `base.py` 第 49 行 |

## 5. 源码逐段精读

> **进阶提醒：** 公共管线见第 04 篇；这一节只读 PSO 自己的 33 行。

![图 1　PSO 一代的代码调用链：上排中文动作、下排代码定位](architecture/06_pso_flow.png)

**图 1　代码调用链**（可编辑 Visio 源：[06_pso_flow.vsdx](architecture/06_pso_flow.vsdx)）

![图 2　PSO 代码模块架构：跨代状态 / 速度更新 / 解码 / 输出](architecture/06_pso_arch.png)

**图 2　代码模块架构**（可编辑 Visio 源：[06_pso_arch.vsdx](architecture/06_pso_arch.vsdx)）

**怎么读这两张图：** 每个节点**上排是中文动作说明**，**下排才是文件与函数定位**。例如「惯性权重随代数线性递减」下面写的是 `w = 0.9 - 0.5 * gen / generations`。先读上排理解流程，再看下排找源码。PNG 与 VSDX 文字完全一致。

### 5.1 基类里的三个跨代状态

**定位：`ai/evolution/base.py` 第 49—62 行（节选）**

```python
def _reset_search(self) -> None:
    self._evaluated = 0
    self._fitness_cache = {}
    self._best_score = VERY_BAD
    ...
    # 供 PSO / ABC 复用的跨代状态
    self._velocity = None
    self._pbest = None
    self._pbest_scores = None
    self._trials = None
```

**逐行看懂：** PSO 和 ABC 的专属状态放在基类，是因为四种算法共用同一个 `select_move()` 生命周期；`select_move()` 开头会调 `_reset_search()`，所以这些状态**只在一次落子的多代之间保留**，下一回合重新建。

### 5.2 完整的 `_step()`

**定位：`ai/evolution/optimizers.py` 第 111—143 行（节选）**

```python
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

    new_pop = []
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
```

**逐行看懂：**

1. 初始化分支只在 `_velocity is None` 时执行一次；`_pbest` 用 `list(v)` 做**浅拷贝**，避免后续原地修改把历史最优也改掉。
2. `w` 的递减与 `1.6`、`±0.3` 都是**写死在源码里的常数**，不在 `settings.py`，也不在命令行。想调风格要改这个文件（见第 7 节）。
3. `gbest` 取自 `_pbest_scores` 的 `max`，不是本代 `scores` 的 `max`。
4. `nx.append((pos[d] + v) % 1.0)`：Python 的 `%` 对负数也返回非负结果，所以回绕天然安全。
5. 与 DE 不同，PSO 用**整代** `_assess_population()`（能用 numpy 批量打分），效率优势在这里。

### 5.3 本节小结：把函数名串起来

```
ai/evolution/base.py · EvolutionaryAI.select_move()   （第 04 篇）
  └─ for gen in 1..EVO_GENERATIONS:
     └─ ai/evolution/optimizers.py · ParticleSwarmAI._step()
        ├─ 首次：_velocity / _pbest / _pbest_scores 初始化
        ├─ w = 0.9 - 0.5 * min(1, gen/G)
        ├─ gbest = _pbest[argmax(_pbest_scores)]
        ├─ 逐粒子逐维：v = w*vel + 1.6*r1*(pbest-x) + 1.6*r2*(gbest-x)
        ├─ v 限幅 ±0.3；x = (x + v) % 1.0
        ├─ base.py · _assess_population() → kernel.decode() / batch_scores()
        └─ if s > _pbest_scores[i]: 刷新 _pbest
```

| 常量 / 字段 | 定义处 | 含义 |
| --- | --- | --- |
| `w` | `_step()` 内 | 0.9 → 0.4 线性递减 |
| 认知 / 社会系数 | `_step()` 内 | 1.6 / 1.6 |
| 速度上下限 | `_step()` 内 | ±0.3 |
| 初始速度范围 | `_step()` 内 | `[-0.1, 0.1]` |
| `_velocity` / `_pbest` | `base.py · _reset_search()` | 跨代但**不跨回合** |

## 6. 代码模块地图

| 文件 | 类 / 函数 | 作用 | 被谁调用 | 建议读码顺序 |
| --- | --- | --- | --- | --- |
| `ai/evolution/optimizers.py` | `ParticleSwarmAI._step()` | **PSO 的一代算子** | 基类主循环 | ① |
| `ai/evolution/base.py` | `_reset_search()` | 清空跨代状态 | `select_move()` 开头 | ② |
| `ai/evolution/base.py` | `_assess_population()` | 整代解码 + 批量打分 | `_step()` | ③ |
| `ai/evolution/kernel.py` | `decode()` / `fitness()` | 向量解码与适应度 | `_assess_population()` | ④ |
| `ai/accel/batch.py` | `batch_scores()` | numpy / CUDA 批量局面打分 | `_assess_population()` | ⑤ |
| `ai/evolution/base.py` | `_publish()` / `_record()` | 播报进度、维护全局最优 | 每代末尾 | ⑥ |
| `ai/candidates.py` | `current_candidates()`（经 kernel） | 实时合法步清单 | `decode()` | ⑦ |
| `config/settings.py` | `EVO_*` 系列 | 四种算法共用预算 | `load_config()` | ⑧ |

**推荐读码路线：** 第 04 篇 `select_move()` + `decode()` → 本篇 ① `_step()` → ② `_reset_search()`（理解「为什么不跨回合」）→ ③ `_assess_population()`（理解整代批量）。

## 7. 动手试一试

```bash
# PSO 对随机基线
python start.py --game gomoku --mode ai_vs_ai --p1-ai pso --p2-ai random --seed 42

# 四种进化算法两两 PK，感受收敛风格差异
python start.py --game chess --mode ai_vs_ai --p1-ai pso --p2-ai abc --evo-time 5 --seed 42

# 缩小种群，观察「全群过早收拢」
python start.py --game gomoku --mode ai_vs_ai --p1-ai pso --p2-ai random --evo-population 6 --seed 42
```

| 参数 | 默认值 | 调大之后会看到什么 |
| --- | --- | --- |
| `--evo-population` | 50 | 粒子更多、多样性更好，每代更慢 |
| `--evo-generations` | 500 | 迭代更多轮，`w` 也衰减得更多 |
| `--evo-horizon` | 6 | 维度更高，收敛明显变难 |
| `--evo-time` | 20.0 秒 | 与代数构成双预算，先到即停 |

> **初学者提示：** `w`、`1.6`、`±0.3` 是源码常量，不在命令行里。想直观感受「探索 vs 收敛」，改 `1.6` 两个系数或 `w` 的递减幅度比改预算更明显，改完记得加 `--seed 42` 做前后对比。

## 8. 常见疑问与已知限制

**问：为什么 PSO 通常比 GA / DE 收敛快？**

答：因为所有粒子都被 `gbest` 直接牵引，信息是全群共享的；代价是也更容易一起陷入同一个局部最优。

**问：速度越界要处理吗？**

答：见 5.2。项目只对**位置**做 `% 1.0` 回绕，速度用 `max/min` 限幅但不回绕。位置始终可解码，因此不会产生非法着法。

**问：为什么每次选步都要清空 `_velocity` / `_pbest`？**

答：不同棋局的合法步清单完全不同，上一局的速度与最优向量在这一局没有意义，沿用只会把搜索带偏。它们是「跨代」状态，不是「跨回合」状态。

**问：GPU 能把 PSO 加速很多吗？**

答：只能加速 `batch_scores()` 那一步的批量局面打分。推演过程是串行、不规则的树形分支，GPU 帮不上这部分。

- 已知限制：离散棋步空间里「速度」缺乏严格几何意义。
- 已知限制：对手模型只有一层贪心（第 04 篇），棋力定位为对照基线。
- 已知限制：认知 / 社会系数与惯性衰减写死在源码里，不是可调参数。
- 适合场景：小规模连续参数寻优（评估函数权重）收敛最快；本项目四种群体算法里，PSO 在象棋 2 秒预算下吞吐提升最明显。
- 文档定位：代码片段是节选，完整实现以 `ai/evolution/optimizers.py` 为准。

---

*ACBP 棋类综合对战平台 · 算法学习文档 · 第 06 篇 / 共 10 篇 · 代码片段基于 2026-11-10 源码*
