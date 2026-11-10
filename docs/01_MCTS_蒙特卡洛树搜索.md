# 01　MCTS：靠「多试几次」下棋

> 选择 → 扩展 → 模拟 → 回传，逐行读 `ai/mcts.py`

**编号 01　|　难度：进阶　|　建议阅读：35 分钟　|　前置：第 00 篇（统一接口与调用链）**

[← 返回文档导航](README.md)　|　上一篇：[00 算法体系总览](00_算法体系总览.md)　|　下一篇：[02 Alpha-Beta 剪枝搜索](02_AlphaBeta_剪枝搜索.md)

> **30 秒速览：** 不知道哪一步好？那就把每一种可能反复「在脑子里下完」，统计各自赢了多少次，最后选胜率最高的那一步。MCTS 把这件事组织成一棵搜索树，用 UCT 公式平衡「试老路」与「探新路」。这一篇会**逐段读 `ai/mcts.py` 的真实源码**：四个超参数、树节点、主循环、四阶段函数、最终选步，以及它们调用的 `candidates.py` / `evaluator.py` / `helpers.py`，读完你应该能自己打开源码顺着看下去。

> **源码快照说明：** 本文所有代码片段基于 **2026-11-10** 的项目源码，均为**节选**（省略处用注释标明）。行号只用于对照，**「函数名」才是稳定定位**；代码改动后请以函数名为准。

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

一句话：MCTS 不靠精确推演，而靠大量随机模拟的统计结果来选步。

读完你应该能回答：

- 「模拟一局」到底模拟了什么，和真的下完一局一样吗？
- UCT 公式在源码里是哪几行，为什么不能只挑当前胜率最高的？
- 为什么项目里还要先做「强制预检」，不直接全部交给 MCTS？
- 最终选步到底看胜率还是访问次数？**源码里的答案比「取最高胜率」更细。**

**这一篇会带你读的文件：** `ai/mcts.py`（主体）、`ai/candidates.py`、`ai/evaluator.py`、`ai/base_ai.py`、`ai/think_state.py`、`utils/helpers.py`、`config/settings.py`。

> **初学者提示：** 先记住一个画面：你站在岔路口有 3 条路，不知道哪条通向山顶，于是每条路派 100 个分身去走，哪条回来的人最多，你就走哪条。第 5 节只是把这个画面翻译成代码。

## 2. 先用直觉理解

人类棋手遇到陌生局面时，常会说「我大概摆一摆」：假设我走这儿、他大概应那儿、我再走这儿……摆上几遍，凭感觉哪条线舒服就选哪条。MCTS 就是把这件「摆一摆」自动化、并且把「凭感觉」换成「数胜率」。

它有两个朴素的好处：不需要把棋局评估写得极其精确，也不怕分支特别多（围棋、五子棋这种一步有几十上百个候选的局面）。

代价是：模拟本身带随机性，得试够多次结论才稳，所以需要时间预算。

> **初学者提示：** 项目里的模拟并不是「完全随机瞎下」：`_HEURISTIC_ROLLOUT_PROB = 0.7`，即有 70% 的概率走带战术意识的启发式步，只有 30% 纯随机。这是为了让有限的模拟次数更有价值。

## 3. 跟着代码走一遍

> **这一节是整篇最关键的部分。** 假设轮到 AI，棋盘上有 3 个值得考虑的落点 A、B、C，预算 100 次模拟。下面按真实执行顺序走 9 步，每一步都先讲清「这一步在干什么」，再解释**那个英文函数具体做了什么**、给它什么、还回什么、为什么非要它。第 5 节会把这些片段的源码逐行摊开，这里先把流程读懂。

### 先收好这张「函数名对照表」

英文函数名看过就忘很正常，本篇涉及的函数全在这里，随时回来查：

| 函数名（英文） | 中文作用（它到底干了什么） | 输入 → 输出 |
| --- | --- | --- |
| `MCTSAI.select_move()` | MCTS 的总入口：预检 → 反复模拟 → 返回最终落子 | 棋盘 + 进度回调 → `(row, col)` |
| `candidate_moves()` | 先取全部合法步，再把五子棋候选裁剪到已有棋子 2 格邻域内 | 棋盘 → 坐标列表 `legal` |
| `MoveTimer` | 计时器，`timeout` 属性回答「时间到了没」 | 秒数上限 → `True/False` |
| `_begin_think()` | 清空上一轮的思考状态，准备给界面播报新进度 | 无 → 重置 `ThinkState` |
| `_forced_move()` | 转发到公共战术预检，问「有没有必胜 / 必挡的棋」 | 棋盘 → `(坐标, 提示文字)` 或 `None` |
| `gomoku_forced_move()` | 四层确定性判断：己方成五 → 堵对手成五 → 己方活四 → 堵对手活四 | 棋盘 + 本方 → 同上 |
| `_MCTSNode` | 搜索树的一个节点，装一份棋盘副本 + 树结构 + 访问/胜场统计 | 棋盘副本等 → 节点对象 |
| `uct_score()` | 算「这个子节点值不值得再试」：平均胜率 + 探索奖励 | 父节点访问数 → 一个分数 |
| `_tree_policy()` | 沿 UCT 一路向下选，遇到没展开完的节点就停下来扩展 | 根节点 → 本轮模拟起点 |
| `_expand()` | 从 `untried_moves` 取一手，复制棋盘落子，挂一个新子节点 | 节点 → 新子节点 |
| `_rollout()` | 从新局面快速模拟下棋，估一个本方胜率 | 局面副本 → `0~1` 的 `outcome` |
| `_heuristic_rollout_move()` | 模拟时挑一手「像人下的」棋（战术优先 / 位置权重） | 局面 + 合法步 → 一步或 `None` |
| `evaluate()` | 没下完时给末局面打分（正数对我有利） | 局面 + 本方 → 分数 |
| `_backpropagate()` | 沿父链把这次结果记回每个节点：`visits += 1`、`wins += outcome` | 节点 + 胜率 → 无 |
| `_select_best_child()` | 过滤掉样本太少的子节点，再按 (胜率, 访问次数) 挑最终落子 | 根节点 → 最优子节点 |
| `_update_top_moves()` | 把访问次数 Top3 的候选写进 `ThinkState`，供棋盘高亮 | 根节点 → 无 |
| `_emit()` | 把当前 `ThinkState` 推给界面回调，画进度条与候选高亮 | 思考状态 → 无 |

### 第 1 步：入口先问「现在能下在哪」

**在干什么：** 拿到当前局面所有**值得考虑**的落点，顺便确认这局还能不能下。

**函数具体做什么：** `MCTSAI.select_move()` 的第一句是 `legal = candidate_moves(board)`。这个 `candidate_moves()`（在 `ai/candidates.py`）先调规则层的 `board.get_legal_moves()` 取全部合法步；若是五子棋，再只保留**已有棋子 `CANDIDATE_RADIUS = 2` 格邻域内**的空位（棋盘还空着时直接给中心附近四点），把候选从全盘 200 多个压到 40~80 个；黑白棋 / 象棋合法步本来就少，直接原样返回。

**输入 → 输出：** 传当前棋盘 `board`，返回坐标列表，例如 `legal = [(7,7), (7,8), (6,7)]`。

**如果为空：** `select_move()` 直接 `return None`。含义是「我无步可下」，由对局层按棋种规则处理——黑白棋自动跳回合，象棋判将死 / 困毙（详见第 00 篇 5.6）。

**为什么：** 分支太多时，5000 次模拟摊到每个落点上根本不够统计；先裁剪，预算才花得值。

### 第 2 步：把「进度条」和「秒表」准备好

**在干什么：** 开始一次全新的思考，把上一轮的进度清掉，并启动计时。

**函数具体做什么：** `self._begin_think()` 调 `ThinkState.reset()`，把 `phase`、`done`、`best_move`、`top_moves` 等十几个字段全部归零；`self.think.total = self.iterations` 把总预算（默认 5000）告诉界面，进度条才知道分母。接着 `MoveTimer(self.time_limit)` 造一个计时器（`utils/helpers.py`），`timer.start()` 记下当前时刻，之后每次问 `timer.timeout` 就是「已过秒数 ≥ 上限了吗」。

**输入 → 输出：** `time_limit = 10.0` 秒 → 一个计时器；`self.think.total = 5000`。

**为什么：** MCTS 有**两个刹车**——迭代次数和思考秒数，哪个先到都停。没有计时器就只能用次数控制，遇到复杂局面会想太久。

### 第 3 步：先检查「有没有一眼就该下的棋」

**在干什么：** 遇到一手能赢、或必须挡的棋，不用模拟，直接下。

**函数具体做什么：** `self._forced_move(board)` 转发给 `ai/candidates.py · gomoku_forced_move()`，后者按四层优先级问：① 我这一步能不能成五？② 对手下一步能不能成五（必须堵）？③ 我能不能做活四？④ 对手能不能做活四（含跳三补中间）？命中就返回 `(坐标, 中文提示)`，例如 `((7,8), "检测到对手成五点，强制防守")`；没命中返回 `None`。这段逻辑**所有算法共用**，避免 MCTS、Alpha-Beta、进化算法各写一份而互相漂移。

**输入 → 输出：** 当前棋盘 + 本方编号 → 一个坐标，或 `None`。

**为什么：** 模拟带随机性，可能把「一手必胜」这种确定结论淹掉。命中时源码会把 `think.note` 设成提示文字、推一次进度、然后**直接返回**，连一次迭代都不消耗。

### 第 4 步：用棋盘副本建一棵新树的根

**在干什么：** 为这次决策造一棵全新的搜索树，根节点就是当前局面。

**函数具体做什么：** `root = _MCTSNode(board.copy(), None, None, board.current_player)`。注意是 **`board.copy()` 副本**——后面所有模拟落子都在副本上，绝不改动真实棋盘。`_MCTSNode` 构造时会立刻调一次 `candidate_moves(state)` 把该局面的候选步算好、用 `sort_moves_by_heuristic()` 排序，存进 `untried_moves`；同时初始化 `visits = 0`（访问次数）、`wins = 0.0`（累计胜场）、`children = []`（子节点）。

**输入 → 输出：** 棋盘副本 + 父节点 `None` + 来步 `None` + 当前行棋方 → 一个 `root` 节点。

**为什么：** 候选步在**建节点时**就算好，扩展阶段只管 `pop()`，不用每一步都重复做邻域裁剪和启发式打分。

### 第 5 步：问一句「还能再试一次吗」

**在干什么：** 决定要不要再来一轮模拟——这就是图 1 右侧那条朱红色回边的起点。

**函数具体做什么：** `while iterations < self.iterations and not timer.timeout:` 同时检查两个条件：已完成的模拟次数还没到 5000，**并且**计时器没超时。两个条件任一不满足就跳出循环去选步。

**输入 → 输出：** `iterations`、`self.iterations`、`timer.timeout` → 继续循环 / 跳出。

**为什么：** 「先到即停」保证最慢也就 10 秒；同时迭代上限防止局面太简单时反复空转。

### 第 6 步：选择 + 扩展，找到本轮模拟的起点

**在干什么：** 在树里往下走，挑出一个「这次该从哪儿开始模拟」的新局面。

**函数具体做什么：** `self._tree_policy(root)` 是个循环：如果当前节点还有没试过的走法（ `fully_expanded` 为假），就调 `self._expand(node)` —— 从 `untried_moves` 取一手、复制一份棋盘、落子、造一个新 `_MCTSNode` 挂到 `children`，然后**返回这个新子节点**；如果已经完全展开，就用 `best_child_by_uct()` 按 `uct_score()` 的分数挑一个子节点继续往下走。`uct_score()` 算的是「平均胜率 `winrate` + 探索奖励 `0.25 × √(ln(父访问数)/本节点访问数)`」——试得少、胜率高的会被优先照顾。

**输入 → 输出：** `root` → 一个叶子节点 `node`（它自带一份 `node.state` 棋盘副本）。

**为什么：** 这就是 MCTS 四阶段的①选择 + ②扩展。它把有限的模拟次数导向「有希望但还没试够」的分支，而不是平均撒胡椒面。

### 第 7 步：快速模拟，估一个「本方赢面」

**在干什么：** 从这个新局面出发，飞快地把棋「摆完」，得到一个 0~1 的胜率估计。

**函数具体做什么：** `self._rollout(node.state)` 又复制一份棋盘（`sim = state.copy()`），然后循环落子：每一步以 70% 概率调 `_heuristic_rollout_move()` 挑一手像样的棋（黑白棋按位置权重加权随机、五子棋先走 `_tactical_move()` 的成五/堵五/成四战术），否则 `random.choice(legal)` 纯随机。五子棋只模拟 **12 步**就停，没分胜负时调 `ai/evaluator.py · evaluate(sim, self.player)` 给末局面打分，再用 `0.5 + 0.45 × tanh(score / 120.0)` 把分数压成 0.05~0.95 的胜率；黑白棋则一直下到终局，按真实胜负返回 `1.0 / 0.5 / 0.0`。

**输入 → 输出：** `node.state` → `outcome`，例如 `0.62`（估计本方有 62% 赢面）。

**为什么：** 五子棋纯随机下到终局，结果往往由「谁先碰巧凑成五」决定，噪声会盖过「堵活三」的价值；短模拟 + 局面打分更稳。

### 第 8 步：把结果记回这条路上的每个节点

**在干什么：** 让这次模拟的结论，变成树里的统计数据。

**函数具体做什么：** `self._backpropagate(node, outcome)` 是个 `while node is not None` 的循环：给当前节点 `visits += 1`、`wins += outcome`，然后 `node = node.parent` 一路往回走，直到根节点。注意**全树统一按「本方（根节点一方）视角」记胜率**，中间不翻转符号，这样后面直接取最大胜率就是对的方向。

**输入 → 输出：** `node` + `outcome = 0.62` → 路径上每个节点的 `visits` 都 +1、`wins` 都 +0.62。

**为什么：** 这是四阶段的④回传。没有它，前面 100 次模拟等于白算，树里什么都没留下。

### 第 9 步：挑出最终落子，并把候选告诉界面

**在干什么：** 模拟用完，从根节点的几个孩子里选出真正要下的那一步。

**函数具体做什么：** 先由 `self._select_best_child(root)` 算一个**最小样本量** `min_samples = max(3, root.visits // 子节点数 // 3)`，只在访问次数达标的子节点里按 `(胜率, 访问次数)` 取最大；若一个都不达标（预算极小），才退回整池比较。**不是简单取最高胜率**——「只试 1 次、赢 1 次 = 100%」是假象，必须过滤掉。接着 `self._update_top_moves(root)` 把**访问次数 Top3** 的候选（坐标、次数、胜率）写进 `ThinkState.top_moves`，`_emit()` 推给界面画高亮；最后 `return best_child.move`。

**输入 → 输出：** `root` → 一个坐标，例如 `(7, 8)`；同时界面拿到 Top3 候选表与 `best_value`。

**为什么：** 决策和展示用两套标准：决策看「样本够 + 胜率高」，展示按「访问次数」排序，因为访问次数代表算法真正投入过预算的位置。

> **一句话记住整条链：** 先裁剪候选（`candidate_moves`）→ 再排除必胜/必挡（`gomoku_forced_move`）→ 建树（`_MCTSNode`）→ 在预算内反复做「选择+扩展（`_tree_policy`）→ 模拟（`_rollout`）→ 回传（`_backpropagate`）」→ 最后挑一个样本够、胜率最高的子节点（`_select_best_child`）落子。
>
> 上面每一步的**真实源码片段与逐行解释**在第 5 节；图 1 的红色回边就是第 5→8 步的循环。

## 4. 名词速查

| 名词 | 大白话 | 在项目里的取值 / 位置 |
| --- | --- | --- |
| 节点 Node | 树里的一个局面副本 | `ai/mcts.py · class _MCTSNode` |
| `untried_moves` | 该节点还没展开过的候选步列表 | 节点构造时算好，`_expand()` 里逐步 `pop()` |
| `visits` / `wins` | 访问次数 / 累计胜场（平局记 0.5） | `_MCTSNode` 的两个字段 |
| `winrate` | 平均胜率 `wins / visits` | `_MCTSNode.winrate`（属性） |
| UCT | 决定下一个该试谁：既看胜率也看试得够不够 | `_MCTSNode.uct_score()` |
| 探索常数 c | 越大越爱探新路，越小越爱走老路 | `_UCT_EXPLORE = 0.25` |
| Rollout / 模拟 | 从某局面快速下完，估一个输赢 | `MCTSAI._rollout()` |
| `MoveTimer` | 「时间到没到」的计时器 | `utils/helpers.py · MoveTimer.timeout` |
| 双预算 | 次数或时间，哪个先到就停 | `MCTS_ITERATIONS = 5000` / `MCTS_TIME_LIMIT = 10.0` |
| 强制预检 | 一眼能赢 / 必须挡，直接落子不模拟 | `ai/candidates.py · gomoku_forced_move()` |
| 胜率映射 | 没下完时用局面分折算成 0~1 胜率 | `0.5 + 0.45 * tanh(score / 120.0)` |
| `_emit()` | 把 `ThinkState` 推给界面的那一下 | `ai/base_ai.py · BaseAI._emit()` |

## 5. 源码逐段精读

> **进阶提醒：** 这一节按 `ai/mcts.py` 文件头自己给的阅读顺序展开。建议把源码放在旁边对照；只想会用、会调参的话，看完两张图和 5.4 就可以跳到第 7 节。

### 先看两张代码模块图

![图 1　MCTS 一步决策的代码调用链：节点标出文件与函数](architecture/01_mcts_flow.png)

**图 1　代码调用链**（可编辑 Visio 源：[01_mcts_flow.vsdx](architecture/01_mcts_flow.vsdx)）。右侧朱红色回边就是 `select_move()` 里的 `while` 循环：`_backpropagate()` 之后 `iterations += 1`，回到预算判断。

![图 2　MCTS 代码模块推理架构：树结构、四阶段、辅助模块、输出](architecture/01_mcts_arch.png)

**图 2　代码模块架构**（可编辑 Visio 源：[01_mcts_arch.vsdx](architecture/01_mcts_arch.vsdx)）。左列是模块职责，右列是 `ai/mcts.py` 里的类与函数，以及它们依赖的 `ai/candidates.py`、`ai/evaluator.py`、`utils/helpers.py`。

**怎么读这两张图：** 每个节点**上排是中文动作说明**（这一步在做什么、为什么要做），**下排才是 `ai/mcts.py` 里的函数定位**。例如「裁剪出值得考虑的落点，少走冤枉路」下面写的是 `candidate_moves(board) → legal`。先读上排理解流程，再看下排找源码。两张图的 PNG 与 VSDX 由同一份节点定义生成，文字完全一致；架构图的纵向箭头表示分层依赖，不是逐行调用。

### 5.1 文件头已经写好了「阅读顺序」

**定位：`ai/mcts.py` 第 1—40 行（模块 docstring 节选）**

```python
"""
蒙特卡洛树搜索(Monte Carlo Tree Search, MCTS)—— 强化版。

【本文件在项目中的位置】
本文件是「MCTS 算法」的完整实现,对局层通过 ai/factory.py 按名称 'mcts'
实例化 MCTSAI,再由 game/controller.py 的 step_ai() 调用 select_move()。
算法本身不依赖 pygame,也不关心具体棋种 ...

【阅读顺序建议】
    常量 → _MCTSNode(树节点数据结构)→ MCTSAI.select_move(主流程)
    → _forced_move(预检)→ _tree_policy / _expand(选择与扩展)
    → _rollout / _heuristic_rollout_move / _tactical_move(模拟)
    → _backpropagate(回传)→ _select_best_child / _update_top_moves(选步与展示)
"""
```

**为什么先读这段：** 这个 docstring 已经把「谁调用我」「我依赖谁」「按什么顺序读」写清楚了，本节的 5.2—5.9 就是照这个顺序走。养成**先读文件头注释**的习惯，比一上来从第一行代码硬啃快得多。

再看导入（第 46—55 行），能直接看出这个模块的依赖边界：

```python
from .base_ai import BaseAI
from .candidates import (candidate_moves, gomoku_winning_moves,
                         gomoku_attack_points, gomoku_defense_points,
                         gomoku_forced_move, sort_moves_by_heuristic, is_near_stone)
from .evaluator import evaluate, _OTHELLO_WEIGHTS
from core.base_board import DRAW, EMPTY
from utils.helpers import MoveTimer
```

- `.base_ai` → 统一接口（第 00 篇 5.5）
- `.candidates` / `.evaluator` → 候选裁剪与局面打分
- `core.base_board` → 只拿常量，不碰具体棋种实现
- `utils.helpers` → 计时器
- **没有 import pygame** → 算法层与界面完全解耦

### 5.2 四个超参数常量

**定位：`ai/mcts.py` 第 66—80 行（节选注释 + 赋值）**

```python
# UCT 探索常数 C：C 越大越倾向访问次数少的分支(探索)，越小越倾向高胜率(利用)。
# 五子棋候选点多(40~80)、rollout 噪声大，经典 sqrt(2)≈1.414 会让访问被打散；
# 这里取 0.25 强利用，把预算花在更有希望的分支上。
_UCT_EXPLORE = 0.25

# 每次模拟选步时，以 0.7 的概率走启发式步，0.3 的概率随机走一步。
_HEURISTIC_ROLLOUT_PROB = 0.7

# 五子棋短模拟步数上限，超过后改用局面评估。
_ROLLOUT_STEPS = 12

# 局面评估分 → 胜率的 tanh 缩放系数。
_EVAL_SCALE = 120.0
```

| 常量 | 值 | 用在哪 | 调大之后 |
| --- | --- | --- | --- |
| `_UCT_EXPLORE` | `0.25` | `_MCTSNode.uct_score()` | 更爱探索冷门分支，胜率收敛变慢 |
| `_HEURISTIC_ROLLOUT_PROB` | `0.7` | `_rollout()` | 模拟更「聪明」但多样性下降 |
| `_ROLLOUT_STEPS` | `12` | `_rollout()`（仅五子棋） | 模拟更长、更慢，噪声可能变大 |
| `_EVAL_SCALE` | `120.0` | `_rollout()` 的 tanh 映射 | 胜率差异被压得更平 |

> **为什么这些是「文件内常量」而不是 `settings.py`：** 它们属于算法内部的实现细节，调它们需要理解 MCTS；而 `MCTS_ITERATIONS` / `MCTS_TIME_LIMIT` 是给使用者的「预算旋钮」，才放在 `config/settings.py` 并开放命令行覆盖（见第 7 节）。

### 5.3 树节点：`class _MCTSNode`

**定位：`ai/mcts.py` 第 97—134 行（节选）**

```python
def __init__(self, state, parent, move, player) -> None:
    self.state = state                    # 该节点对应的棋盘局面副本
    self.parent = parent                  # 父节点引用（根节点为 None）
    self.move = move                      # 走到本节点的那一步棋
    self.player = player                  # 本局面中将要落子的玩家
    self.children: List[_MCTSNode] = []

    # 候选走法：先邻域裁剪，再按启发式分数降序排列
    self.untried_moves = candidate_moves(state)
    if len(self.untried_moves) > 1:
        self.untried_moves = sort_moves_by_heuristic(
            state, self.untried_moves, player)
        # 五子棋：把对手活三 / 冲三的防守点直接挪到列表前部
        if type(state).__name__ == "GomokuBoard":
            defs = gomoku_defense_points(state, player)
            if defs:
                self.untried_moves = (
                    [m for m in defs if m in self.untried_moves]
                    + [m for m in self.untried_moves if m not in defs])

    self.visits = 0                       # 被访问次数
    self.wins = 0.0                       # 累计胜场（平局计 0.5）

@property
def winrate(self) -> float:
    return self.wins / self.visits if self.visits else 0.0
```

**逐行看懂：**

1. `state` 是**棋盘副本**，不是引用。`_expand()` 里用 `state.copy()` 造子节点，所以模拟时怎么落子都不会污染真实棋盘——`select_move()` 的 docstring 专门强调了「本方法不会修改它」。
2. `untried_moves` 在节点**创建时**就算好并排序，扩展阶段只 `pop()`，不重复做邻域裁剪和启发式打分。这是性能上的关键设计。
3. 五子棋那段列表推导把防守点 `[m for m in defs ...] + [其余]` 拼到前面，保证「该堵的先堵」在搜索早期就被覆盖。
4. `winrate` 用 `if self.visits else 0.0` 防除零：新节点还没被访问过，胜率按 0 处理。

**UCT 公式在源码里的样子**（第 136—153 行）：

```python
def uct_score(self, parent_visits: int) -> float:
    exploit = self.winrate
    explore = _UCT_EXPLORE * math.sqrt(
        math.log(parent_visits) / self.visits)
    return exploit + explore

def best_child_by_uct(self):
    return max(self.children, key=lambda child: child.uct_score(self.visits))
```

- `exploit = winrate`：当前平均胜率，鼓励利用已知好路。
- `explore` 里 `self.visits` 在分母：试得越少，这一项越大；`math.log(parent_visits)` 让父节点访问越多，探索奖励越明显。
- `best_child_by_uct()` 用 `max(..., key=...)` 选出得分最高的子节点，`_tree_policy()` 靠它逐层下行。

> **读码提示：** `math.log(parent_visits)` 要求 `parent_visits > 0`。源码里只有在节点已完全展开（`fully_expanded`）时才会调 `best_child_by_uct()`，此时父节点一定被访问过，所以不会踩 `log(0)`。

### 5.4 主流程：`MCTSAI.select_move()`

先看构造函数（第 168—178 行），预算从这里进来：

```python
def __init__(self, player, config) -> None:
    super().__init__(player, config)
    self.iterations = max(1, int(config.mcts_iterations))
    self.time_limit = float(config.mcts_time)
```

`config.mcts_iterations` / `config.mcts_time` 正是第 00 篇 5.2 里 `Config` 的字段，`max(1, ...)` 保证至少迭代一次。

**第 1 段：候选裁剪与计时（第 199—208 行）**

```python
legal = candidate_moves(board)
if not legal:
    return None

self._begin_think()                    # 重置 ThinkState
self.think.total = self.iterations
timer = MoveTimer(self.time_limit)
timer.start()
```

`candidate_moves()` 在 `ai/candidates.py` 第 42 行：黑白棋 / 象棋直接返回全部合法步，五子棋只保留已有棋子 `CANDIDATE_RADIUS = 2` 格邻域内的空位（空盘时返回中心四点）。这一步把五子棋分支因子从全盘 200+ 降到 40~80，是能跑得动的前提。

`MoveTimer` 在 `utils/helpers.py` 第 20 行，核心就一个属性：

```python
@property
def timeout(self) -> bool:
    if self.limit <= 0:
        return False
    return (time.perf_counter() - self._start) >= self.limit
```

**第 2 段：强制预检（第 210—220 行）**

```python
quick_move = self._forced_move(board)
if quick_move is not None:
    self.think.phase = "强制预检"
    self.think.best_move = quick_move
    self.think.done = 1
    self._emit(on_progress)
    self.think.finish()
    return quick_move
```

注意这里**不消耗搜索预算**：确定性战术结论优先于带噪声的统计。即使提前返回，也要走 `_emit()` 和 `finish()`，让界面的进度条能正常收尾。

**第 3 段：主循环（第 222—243 行）**

```python
root = _MCTSNode(board.copy(), None, None, board.current_player)
iterations = 0
emit_interval = max(5, min(200, self.iterations // 50))

while iterations < self.iterations and not timer.timeout:
    node = self._tree_policy(root)          # 选择 + 扩展
    outcome = self._rollout(node.state)     # 0~1 的本方胜率估计
    self._backpropagate(node, outcome)      # 回传统计
    iterations += 1

    if iterations % emit_interval == 0:
        self.think.done = iterations
        self.think.elapsed = timer.elapsed()
        self.think.phase = f"MCTS 模拟中 · {iterations}/{self.iterations}"
        self._update_top_moves(root)
        self._emit(on_progress)
```

**逐行看懂：**

1. 根节点传 `board.copy()`，注释明确写了「后续所有扩展 / 模拟都不会影响真实棋盘」。
2. `while` 的两个条件就是**双预算**：迭代数 `self.iterations` 与 `timer.timeout`，哪个先到都停。
3. 循环体三行正是四阶段中的「选择+扩展 → 模拟 → 回传」（`_tree_policy` 内部包含扩展）。
4. `emit_interval = max(5, min(200, self.iterations // 50))` 约为总迭代的 2%，至少 5 次、至多 200 次才推一次进度。**不是每轮都推**——每轮回调会让界面疯狂重绘。
5. `_update_top_moves(root)` + `_emit()` 把当前 Top3 候选送到界面（对应第 00 篇 5.8 的 `ThinkState.top_moves`）。

**第 4 段：最终选步与收尾（第 245—265 行）**

```python
if not root.children:
    self.think.finish()
    return legal[0]                        # 极端兜底：一次都没扩展成功

best_child = self._select_best_child(root)
self.think.best_move = best_child.move
self.think.best_value = best_child.winrate
self.think.done = iterations
self.think.elapsed = timer.elapsed()
self._update_top_moves(root)
self.think.phase = "完成搜索"
self._emit(on_progress)

log_debug(f"{self.label} MCTS 完成 {iterations} 次迭代, ...")
self.think.finish()
return best_child.move
```

`if not root.children` 是防「预算瞬间耗尽、一个子节点都没建出来」的兜底，保证始终返回合法走法。`log_debug(...)` 只有在 `--debug` 开启时才打印，正好对应第 7 节的调试命令。

### 5.5 预检跨文件：`_forced_move()` → `gomoku_forced_move()`

**定位：`ai/mcts.py` 第 269—281 行**

```python
def _forced_move(self, board):
    result = gomoku_forced_move(board, self.player)
    if result is not None:
        move, note = result
        self.think.note = note
        return move
    return None
```

它只是薄薄一层转发，真正的四层判断在 `ai/candidates.py` 第 200—237 行：

```python
def gomoku_forced_move(board, player):
    if type(board).__name__ != "GomokuBoard":
        return None                       # 非五子棋不预检
    opponent = board.opponent(player)

    my_wins = gomoku_winning_moves(board, player)
    if my_wins:
        return my_wins[0], "发现制胜点，直接成五"
    opp_wins = gomoku_winning_moves(board, opponent)
    if opp_wins:
        return opp_wins[0], "检测到对手成五点，强制防守"
    attacks = gomoku_attack_points(board, player)
    if attacks:
        return attacks[0], "己方活三成四，抢先制造活四"
    opp_attacks = gomoku_attack_points(board, opponent)
    if opp_attacks:
        return opp_attacks[0], "检测到对手活三 / 跳三成活四点，强制堵点"
    defs = gomoku_defense_points(board, player)
    if defs:
        return defs[0], "检测到对手活三 / 跳三，堵端防守"
    return None
```

**为什么单独放一个文件：** docstring 写得很直白——「供 MCTS / Alpha-Beta / 群体优化 AI 共用，避免三份预检逻辑各自漂移」。返回的第二项 `note` 会塞进 `ThinkState.note`，界面上就能显示「检测到冲四，强制防守」。

### 5.6 选择与扩展：`_tree_policy()` / `_expand()`

**定位：`ai/mcts.py` 第 285—318 行**

```python
def _tree_policy(self, node):
    while not node.state.game_over:
        if not node.fully_expanded:
            return self._expand(node)      # 还有没试过的走法 → 立刻扩展
        node = node.best_child_by_uct()    # 已完全展开 → 按 UCT 继续下行
    return node                            # 终局节点直接交给 rollout

def _expand(self, node):
    move = node.untried_moves.pop()        # 从列表尾部取一手
    child_state = node.state.copy()
    child_state.apply_move(move)
    child = _MCTSNode(child_state, node, move, child_state.current_player)
    node.children.append(child)
    return child
```

**逐行看懂：**

1. `fully_expanded` 是个属性，实现就一句 `return not self.untried_moves`——列表空了就算完全展开。
2. 返回的节点就是本轮**模拟的起点**。注意 `while not node.state.game_over`：走到终局节点就停下，不再扩展。
3. `_expand()` 里 `pop()` 取的是列表**尾部**，而 5.3 的 `sort_moves_by_heuristic()` 是**降序**（`sorted(..., key=lambda m: -move_heuristic_score(...))`，见 `ai/candidates.py` 第 310—311 行），所以实际**先被展开的是评分最低的步**；被挪到最前面的防守点反而最后才展开。这与 `sort_moves_by_heuristic()` 文档字符串里「评分高的优先搜索 / 优先扩展」的说法存在出入。**读源码要以实际代码行为为准，不要只信注释**——这正是「参照代码」最值得养成的习惯。
4. `child_state = node.state.copy()` 再次强调「副本」：父节点局面保持不动，回传时才能沿 `parent` 链正确更新。

### 5.7 模拟：`_rollout()` 与它的三个辅助函数

**定位：`ai/mcts.py` 第 322—373 行（节选）**

```python
def _rollout(self, state) -> float:
    sim = state.copy()
    kind = type(sim).__name__
    max_steps = sim.size * sim.size
    steps = 0

    while not sim.game_over and steps < max_steps:
        if kind == "GomokuBoard" and steps >= _ROLLOUT_STEPS:
            break                          # 五子棋短模拟到步数即停
        legal = sim.get_legal_moves()
        if not legal:
            break
        move = None
        if random.random() < _HEURISTIC_ROLLOUT_PROB:
            move = self._heuristic_rollout_move(sim, legal)
        if move is None:
            move = random.choice(legal)
        if hasattr(sim, "fast_apply"):
            sim.fast_apply(move)
        else:
            sim.apply_move(move)
        steps += 1

    if sim.game_over:                      # 情况 A：走到终局，按真实胜负
        if sim.winner == self.player:
            return 1.0
        if sim.winner == DRAW or sim.winner == EMPTY:
            return 0.5
        return 0.0

    score = evaluate(sim, self.player)     # 情况 B：未终局，评估分折算胜率
    return 0.5 + 0.45 * math.tanh(score / _EVAL_SCALE)
```

**逐行看懂：**

1. 又见 `state.copy()`：模拟绝不能改动树里的节点局面。
2. `kind == "GomokuBoard" and steps >= _ROLLOUT_STEPS` → 五子棋只模拟 12 步就 `break`，因为长随机模拟容易被「谁先碰巧凑成五」主导，噪声极大。黑白棋则会一直走到终局。
3. `random.random() < 0.7` 决定是否走启发式步；即使启发式函数返回 `None`，也会 `random.choice(legal)` 兜底，保证一定能走一步。
4. `hasattr(sim, "fast_apply")` 是给象棋等提供的跳过重复规则校验的快速落子入口（源码注释：「模拟步来自合法列表，可跳过重复规则校验」）。
5. 返回值**始终是本方视角的胜率**：终局用 `1.0 / 0.5 / 0.0`；未终局用 `0.5 + 0.45·tanh(score/120)` 把典型的 ±200 评估分压到 0.05~0.95，避免出现 0% / 100% 的极端值。

`_heuristic_rollout_move()`（第 375 行起）按棋种分流：黑白棋用 `_OTHELLO_WEIGHTS` 做加权随机（角 / 边更常被抢）；五子棋先调 `_tactical_move()`；其余情况退到「已有棋子邻域内随机」。`_tactical_move()`（第 409 行起）是五级战术贪婪：

```python
me = sim.current_player
opp = sim.opponent(me)
# 1 自己成五 → 2 对手成五必堵 → 3 自己成四 → 4 对手成四 → 5 返回 None
for m in legal:
    if self._line_after(sim, m, me) >= 5:
        return m
...
```

`_line_after()`（第 445 行）有个很妙的小技巧：

```python
r, c = move
sim.board[r][c] = player          # 临时落子
best = sim._count_line(r, c, player)
sim.board[r][c] = EMPTY           # 立即清空
return best
```

它**直接改 `sim.board` 再改回来**，不经过 `apply_move()`，因此不会触发回合切换、胜负判定或历史记录——只是想问一句「如果下这儿，最长连子数是多少」。读到这里要注意：这种写法只在模拟副本上用，绝不能用在真实棋盘上。

### 5.8 回传：`_backpropagate()`

**定位：`ai/mcts.py` 第 460—477 行**

```python
def _backpropagate(self, node, outcome: float) -> None:
    while node is not None:
        node.visits += 1
        node.wins += outcome
        node = node.parent
```

整个四阶段里最短的函数，但视角约定最关键：docstring 明确写「全树统一按本方（根节点，即本 AI 一方）视角记录胜率」。**不在层间翻转符号**，所以 `best_child_by_uct()` 里对所有子节点直接取 `max(winrate)` 就是最优方向。这是初学实现 MCTS 最常踩的坑——若在每层按「当前行棋方」记胜率，选择逻辑就会整个反过来。

### 5.9 最终选步：`_select_best_child()` / `_update_top_moves()`

**定位：`ai/mcts.py` 第 481—510 行**

```python
def _select_best_child(self, root) -> _MCTSNode:
    min_samples = max(3, root.visits // max(1, len(root.children)) // 3)
    qualified = [c for c in root.children if c.visits >= min_samples]
    pool = qualified or root.children
    return max(pool, key=lambda c: (c.winrate, c.visits))

def _update_top_moves(self, root) -> None:
    ranked = sorted(root.children, key=lambda c: c.visits, reverse=True)[:3]
    self.think.top_moves = [
        (c.move, c.visits, c.winrate) for c in ranked
    ]
```

**逐行看懂：**

1. `min_samples` 是「平均每个子节点应被访问的次数量级」再除以 3，且至少 3 次。
2. 只有在 `qualified`（访问次数达标）的子节点里挑胜率最高的；若一个都不达标（预算极小），`qualified or root.children` 会退回整池比较。
3. `max(..., key=lambda c: (c.winrate, c.visits))` 是**元组比较**：胜率相同才比访问次数。
4. `_update_top_moves()` 按**访问次数**而不是胜率排序取 Top3，源码注释解释得很清楚：访问次数代表搜索实际投入的预算，更能反映算法「认真考虑过」哪些候选，胜率只作辅助展示。

> **这里修正一个常见误解：** 上一版文档写「最终看最高胜率，不是被访问最多」，只对了一半。准确说法是：**先用最小样本量过滤掉统计不可靠的子节点，再按 (胜率, 访问次数) 取最大**；展示用的 Top3 则按访问次数排。两处用的是不同的排序标准。

### 5.10 本节小结：把函数名串起来

```
game/controller.py · step_ai()
  └─ ai/factory.py · create_ai("mcts", ...)
     └─ ai/mcts.py · MCTSAI.select_move(board, on_progress)
        ├─ ai/candidates.py · candidate_moves()        → legal
        ├─ utils/helpers.py · MoveTimer                 → 双预算
        ├─ _forced_move() → ai/candidates.py · gomoku_forced_move()
        ├─ class _MCTSNode(board.copy(), ...)          → root
        ├─ while 预算未耗尽：
        │    ├─ _tree_policy(root) → _expand()
        │    ├─ _rollout(node.state)
        │    │    ├─ _heuristic_rollout_move() / _tactical_move() / _line_after()
        │    │    └─ ai/evaluator.py · evaluate()
        │    └─ _backpropagate(node, outcome)
        └─ _select_best_child(root) / _update_top_moves(root)
           → ai/base_ai.py · _emit() → ui/ai_runner.py · AiRunner.poll()
           → return (row, col)
```

| 常量 / 字段 | 定义处 | 含义 |
| --- | --- | --- |
| `self.iterations` | `MCTSAI.__init__()` | 来自 `config.mcts_iterations`，默认 5000 |
| `self.time_limit` | `MCTSAI.__init__()` | 来自 `config.mcts_time`，默认 10.0 秒 |
| `_UCT_EXPLORE` | `ai/mcts.py` 第 66 行 | 0.25，UCT 探索常数 |
| `_HEURISTIC_ROLLOUT_PROB` | 第 71 行 | 0.7，模拟走启发式步的概率 |
| `_ROLLOUT_STEPS` | 第 75 行 | 12，五子棋短模拟步数 |
| `_EVAL_SCALE` | 第 80 行 | 120.0，评估分 → 胜率的 tanh 缩放 |
| `visits` / `wins` | `_MCTSNode.__init__()` | 访问次数 / 累计胜场 |
| `untried_moves` | `_MCTSNode.__init__()` | 未展开候选（已启发式排序） |

## 6. 代码模块地图

| 文件 | 类 / 函数 | 作用 | 被谁调用 | 建议读码顺序 |
| --- | --- | --- | --- | --- |
| `game/controller.py` | `step_ai()` | 触发一次 AI 回合 | 界面主循环 | ① |
| `ai/factory.py` | `create_ai()` | 按 `"mcts"` 造 `MCTSAI` | `build_players()` / `_worker()` | ② |
| `ai/base_ai.py` | `BaseAI._begin_think()` / `_emit()` | 重置与推送思考状态 | `select_move()` | ③ |
| `ai/mcts.py` | `class _MCTSNode` | 树节点与 UCT 计算 | `_expand()` / `_tree_policy()` | ④ |
| `ai/mcts.py` | `MCTSAI.__init__()` | 读入双预算 | `create_ai()` | ⑤ |
| `ai/mcts.py` | `MCTSAI.select_move()` | 主流程：预检 → 循环 → 选步 | `step_ai()` | ⑥ |
| `ai/mcts.py` | `_forced_move()` | 转发到公共预检 | `select_move()` | ⑦ |
| `ai/mcts.py` | `_tree_policy()` / `_expand()` | 四阶段之选择 + 扩展 | 主循环 | ⑧ |
| `ai/mcts.py` | `_rollout()` + 三个辅助函数 | 四阶段之模拟 | 主循环 | ⑨ |
| `ai/mcts.py` | `_backpropagate()` | 四阶段之回传 | 主循环 | ⑩ |
| `ai/mcts.py` | `_select_best_child()` / `_update_top_moves()` | 最终选步与界面候选 | `select_move()` 收尾 | ⑪ |
| `ai/candidates.py` | `candidate_moves()` / `gomoku_forced_move()` / `sort_moves_by_heuristic()` | 候选裁剪、预检、排序 | 节点构造、预检、`_expand()` | ⑫ |
| `ai/evaluator.py` | `evaluate()` | 未终局时给局面打分 | `_rollout()` | ⑬ |
| `utils/helpers.py` | `MoveTimer` | 时间预算判定 | `select_move()` | ⑭ |
| `config/settings.py` | `MCTS_ITERATIONS` / `MCTS_TIME_LIMIT` | 默认值 5000 / 10.0 | `config/args.py · load_config()` | ⑮ |

**推荐读码路线：** 先按 `ai/mcts.py` 文件头的建议顺序读 ④ → ⑥ → ⑦ → ⑧ → ⑨ → ⑩ → ⑪（这是算法主干）；遇到看不懂的外部函数，再跳到 ⑫ ⑬ ⑭ 查一眼；最后回到 ① ② ③ 看「是谁把它启动起来的」（这部分第 00 篇已讲过）。

## 7. 动手试一试

```bash
# 让 MCTS 与随机基线对打，先感受「统计确实有用」
python start.py --game gomoku --mode ai_vs_ai --p1-ai mcts --p2-ai random --seed 42

# 把模拟次数从 5000 降到 300，观察胜率与思考时间
python start.py --game gomoku --mode ai_vs_ai --p1-ai mcts --p2-ai random --mcts-iterations 300 --seed 42

# 与 Alpha-Beta 同预算对比（五子棋上 AB 通常更强）
python start.py --game gomoku --mode ai_vs_ai --p1-ai mcts --p2-ai alphabeta --mcts-time 10 --ab-time 10

# 打开调试日志，对照 5.4 的 log_debug 看每次迭代统计
python start.py --game gomoku --mode ai_vs_ai --p1-ai mcts --p2-ai random --debug
```

| 参数 | 默认值 | 调大之后会看到什么 |
| --- | --- | --- |
| `--mcts-iterations` | 5000 | 统计更稳、走法更可靠，但每步更慢 |
| `--mcts-time` | 10.0 秒 | 与次数构成双预算，先到即停 |
| `_UCT_EXPLORE`（源码常量） | 0.25 | 调大更爱探索生僻走法，调小更保守 |
| `_HEURISTIC_ROLLOUT_PROB`（源码常量） | 0.7 | 调低会让模拟更随机、噪声更大 |

> **初学者提示：** 想复现同一局，一定加 `--seed 42`（任意整数均可）。否则随机模拟每局都不同，比较两种参数时容易被噪声误导。改源码常量后要重启程序才生效；命令行预算参数则即时生效。

## 8. 常见疑问与已知限制

**问：模拟到终局不就行了，为什么要只模拟 12 步？**

答：见 5.7。五子棋一局可能几十手，纯随机模拟到终局往往由「谁先碰巧凑成五」决定，噪声会把「堵活三」的价值淹没。短模拟后用 `evaluate()` 折算胜率，是用一点精度换大量次数。

**问：最终选步到底看胜率还是访问次数？**

答：**两者都用，但用在不同地方**（见 5.9）。决策时先用 `min_samples` 过滤统计不可靠的子节点，再按 `(胜率, 访问次数)` 取最大；界面展示的 Top3 则按访问次数排序。访问次数多只说明 UCT 觉得它「值得反复确认」，不等于它最好。

**问：为什么一定要按「根节点这一方」统一记胜率？**

答：见 5.8。如果在每层按当前行棋方记胜率，子节点的分数就变成「对方视角」，`max()` 会选出对我最不利的步。源码里 `_rollout()` 的返回值和 `_backpropagate()` 的累加都固定按 `self.player` 视角，正是为了避开这个坑。

**问：`_expand()` 用 `pop()` 取尾部，岂不是先展开了排序最低的步？**

答：是的，这是源码里较绕、且注释与行为不完全一致的一处。`sort_moves_by_heuristic()` 用 `-分数` 做 key 得到**降序**（高分在前），`_expand()` 又用 `pop()` 从**尾部**取，所以先扩展的是低分步；防守点被拼到列表最前，反而最后才扩展。函数 docstring 写的却是「评分高的优先搜索 / 优先扩展」。

以代码为准的结论是：**候选排序主要影响 UCT 的后续选择与 Top 候选的展示，并不保证「高分先扩展」**。如果你想改成高分先扩展，把 `pop()` 换成 `pop(0)`（或把排序改升序）即可，但这会改变搜索顺序，改完请重新跑 `--seed 42` 的对局验证棋力，别只凭直觉判断变强了。

**问：MCTS 和 Alpha-Beta 谁更强？**

答：看棋种。五子棋有很强的领域启发式，同 10 秒预算下本项目 Alpha-Beta 通常更强；分支极大、评估难写的棋种 MCTS 更有优势。

- 已知限制：每个树节点保存一份棋盘副本（`_MCTSNode.state`），内存随迭代次数增长。
- 已知限制：没有置换表与 RAVE 等加速，模拟质量依赖启发式 rollout。
- 已知限制：docstring 提到「不做跨回合复用」，每步都新建整棵树，换局面后旧统计量被丢弃。
- 边界：无合法步时与其它算法一样返回 `None`，由对局层按棋种规则处理。
- 文档定位：代码片段是节选，完整实现请以 `ai/mcts.py` 为准。

---

*ACBP 棋类综合对战平台 · 算法学习文档 · 第 01 篇 / 共 10 篇 · 代码片段基于 2026-11-10 源码*
