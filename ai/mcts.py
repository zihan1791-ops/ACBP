# -*- coding: utf-8 -*-
"""
蒙特卡洛树搜索(Monte Carlo Tree Search, MCTS)—— 强化版。

【本文件在项目中的位置】
本文件是「MCTS 算法」的完整实现,对局层通过 ai/factory.py 按名称 'mcts'
实例化 MCTSAI,再由 game/controller.py 的 step_ai() 调用 select_move()。
算法本身不依赖 pygame,也不关心具体棋种:只要棋盘实现 core/base_board.py
的统一接口(get_legal_moves / apply_move / copy / game_over / winner 等)
即可直接复用,因此同一份代码同时服务五子棋、黑白棋(以及保留的围棋)。

【MCTS 的四个标准阶段】
1. 选择(Selection):从根节点沿 UCT(Upper Confidence Bound applied to Trees,
   置信上界)公式逐层向下,优先选择「胜率高且尝试次数少」的子节点;
2. 扩展(Expansion):走到一个还有未尝试走法的节点时,取出一手棋生成新子节点;
3. 模拟(Rollout / Simulation):从新节点开始快速走棋到终局(或走到预设步数),
   用胜负结果作为该分支的价值估计;
4. 回传(Backpropagation):把模拟结果沿父链向上更新每个节点的访问次数与胜场。

重复以上四步 N 次(受迭代次数与思考时间双约束),最后根据根节点子节点的
统计量选出实际落子。

【本实现相对「教科书版 MCTS」的强化点】
- 候选裁剪:只搜索已有棋子邻域内的空位,把分支因子从全盘 200+ 降到 40~80;
- 启发式先验:候选按棋型分 / 位置权重排序,并把握手可危的防守点前置;
- 强制预检:能成五先成五、对手能成五必堵、己方活三先成活四、对手活三堵端,
  这四层判断在搜索之前直接给出结论,避免搜索预算浪费在必输/必胜局面上;
- 启发式 rollout:五子棋采用「短模拟 + 局面评估」,黑白棋采用「位置权重加权
  随机」,降低纯随机模拟的噪声;
- 最终选步:优先在「访问次数达到最小样本量」的子节点中挑胜率最高者,
  避免被访问次数少、方差大的偶然高胜率走法带偏;
- 思考可视化:通过 ThinkState + on_progress 回调实时向界面推送迭代进度、
  当前最佳步与 Top 候选,界面据此绘制进度条与棋盘高亮。

【阅读顺序建议】
    常量 → _MCTSNode(树节点数据结构)→ MCTSAI.select_move(主流程)
    → _forced_move(预检)→ _tree_policy / _expand(选择与扩展)
    → _rollout / _heuristic_rollout_move / _tactical_move(模拟)
    → _backpropagate(回传)→ _select_best_child / _update_top_moves(选步与展示)
"""

import math
import random
from typing import Optional, Tuple, List

from .base_ai import BaseAI
from .candidates import (
    candidate_moves, gomoku_winning_moves, gomoku_attack_points,
    gomoku_defense_points, gomoku_forced_move,
    sort_moves_by_heuristic, is_near_stone,
)
from .evaluator import evaluate, _OTHELLO_WEIGHTS
from core.base_board import DRAW, EMPTY
from utils.helpers import MoveTimer
from utils.logger import log_debug

# ===================== 算法超参数 =====================

# UCT 探索常数 C:权衡「利用已知优势」与「探索未知分支」。
# UCT 公式为 winrate + C * sqrt(ln(父访问数) / 本节点访问数):
#   - C 越大,越倾向访问次数少的分支(探索);
#   - C 越小,越倾向当前胜率高的分支(利用)。
# 五子棋候选点多(40~80)、rollout 噪声大,经典 sqrt(2)≈1.414 会让访问被
# 均匀打散、胜率无法分辨;这里取 0.25 强利用,让高胜率分支被集中访问,
# 在有限迭代次数内把预算花在更有希望的分支上。
_UCT_EXPLORE = 0.25

# 启发式 rollout 的使用概率(其余比例纯随机,保持一定探索)。
# 每次模拟选步时,以 0.7 的概率走「战术贪婪 / 位置权重」启发式步,
# 以 0.3 的概率随机走一步,避免模拟过程完全确定化、失去多样性。
_HEURISTIC_ROLLOUT_PROB = 0.7

# 五子棋短模拟步数上限:超过后不再继续随机走,改用局面评估(见 _rollout 说明)。
# 原因是五子棋长模拟到终局往往被「随机凑五」的噪声主导,短模拟 + 评估更稳。
_ROLLOUT_STEPS = 12

# 局面评估分 → 胜率的 tanh 缩放系数(棋型分典型量级 ~±200)。
# 映射公式:winrate = 0.5 + 0.45 * tanh(score / 120),把评估分平滑压到
# 0.05~0.95 之间,既保留大小关系,又不会出现 0% / 100% 的极端值。
_EVAL_SCALE = 120.0


class _MCTSNode:
    """
    MCTS 搜索树节点。

    每个节点封装三样东西:
    1. state —— 该节点对应的棋盘局面(一份独立副本,父子节点互不影响);
    2. 树结构 —— parent / children / move,用于向上回传与向下选择;
    3. 统计量 —— visits(被访问次数)与 wins(累计胜场,平局记 0.5),
       UCT 选择与最终选步都只依赖这两个数。

    注意:节点在创建时就把「候选走法」算好并排序(untried_moves),
    这样扩展阶段不需要重复做邻域裁剪与启发式打分。
    """

    def __init__(self, state, parent: Optional["_MCTSNode"],
                 move: Optional[Tuple[int, int]], player: int) -> None:
        self.state = state                                  # 节点代表的棋盘局面副本
        self.parent = parent                                # 父节点引用(根节点为 None)
        self.move = move                                    # 走到本节点的那一步棋(根节点为 None)
        self.player = player                                # 本节点局面中将要落子的玩家
        self.children: List[_MCTSNode] = []                 # 已扩展出的子节点列表

        # 候选走法:先做邻域裁剪,再按启发式分数降序排列(高价值在前)。
        # 这份列表会在扩展阶段被逐步 pop 消耗,全部消耗完表示该节点已完全展开。
        self.untried_moves: List[Tuple[int, int]] = candidate_moves(state)
        if len(self.untried_moves) > 1:
            # 按「己方进攻分 + 对手防守分」排序,让搜索优先展开关键分支
            self.untried_moves = sort_moves_by_heuristic(
                state, self.untried_moves, player)
            # 五子棋:对手活三 / 冲三的防守点前置,优先扩展与访问。
            # 这些点不参与排序打分,而是直接挪到列表前部,保证「该堵的
            # 先堵」在搜索早期就被覆盖,不会被进攻分支挤到后面。
            if type(state).__name__ == "GomokuBoard":
                defs = gomoku_defense_points(state, player)
                if defs:
                    self.untried_moves = (
                        [m for m in defs if m in self.untried_moves]
                        + [m for m in self.untried_moves if m not in defs]
                    )

        self.visits = 0                                     # 节点被访问次数
        self.wins = 0.0                                     # 本节点玩家视角累计胜场(平局计 0.5)

    @property
    def fully_expanded(self) -> bool:
        """是否所有候选走法都已扩展完毕(没有未尝试走法即视为完全展开)。"""
        return not self.untried_moves

    @property
    def winrate(self) -> float:
        """平均胜率(访问次数为 0 时返回 0,避免除零)。"""
        return self.wins / self.visits if self.visits else 0.0

    def uct_score(self, parent_visits: int) -> float:
        """
        计算当前子节点的 UCT 得分:利用项 + 探索项。

        - exploit = self.winrate:当前已统计到的胜率,鼓励利用;
        - explore = C * sqrt(ln(parent_visits) / self.visits):访问越少、
          父节点访问越多,探索奖励越大,鼓励尝试冷门分支。

        返回值为「站在根节点一方视角」的综合评分。
        """
        exploit = self.winrate
        explore = _UCT_EXPLORE * math.sqrt(
            math.log(parent_visits) / self.visits)                         # 探索强度
        return exploit + explore

    def best_child_by_uct(self) -> "_MCTSNode":
        """按 UCT 公式选出得分最高的子节点(用于选择阶段的逐层下降)。"""
        return max(self.children, key=lambda child: child.uct_score(self.visits))


class MCTSAI(BaseAI):
    """
    蒙特卡洛树搜索 AI(启发式强化版)。

    对外只暴露 select_move():给定棋盘,返回一步合法走法。
    内部每次决策都会新建一棵以当前局面为根的搜索树,搜索结束后整棵树丢弃,
    不做跨回合复用(换对手、换局面后旧统计量不再可靠)。
    """

    name = "mcts"
    display_name = "MCTS"

    def __init__(self, player: int, config) -> None:
        """
        参数:
            player: 本方玩家编号(BLACK / WHITE);
            config: 全局配置对象,提供 mcts_iterations(迭代上限)与
                    mcts_time(思考秒数上限)两个预算参数。
        """
        super().__init__(player, config)
        # 每步最大迭代次数 / 最大思考秒数,二者先到即停
        self.iterations = max(1, int(config.mcts_iterations))
        self.time_limit = float(config.mcts_time)

    # ==================== 对外接口:一次完整的决策 ====================

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        """
        执行一轮 MCTS 迭代,返回根节点下最优走法。

        流程总览:
            1. 候选裁剪,得到根节点可考虑的走法;
            2. 强制预检(成五 / 堵五 / 活四 / 堵活三),命中则直接返回;
            3. 建根节点,循环执行「选择 → 扩展 → 模拟 → 回传」直到预算耗尽;
            4. 根据根节点子节点的统计量选出最终落子;
            5. 把最终结论写回 ThinkState 并通知界面。

        参数:
            board:       当前棋盘局面(本方法不会修改它,搜索全部在副本上进行);
            on_progress: 可选回调,接收 ThinkState,用于界面实时可视化。
        返回:
            选中的合法走法;无合法步时返回 None。
        """
        # ---- 0. 候选裁剪:五子棋只保留已有棋子邻域,黑白棋保留全部合法步 ----
        legal = candidate_moves(board)
        if not legal:
            return None

        # 重置思考状态(阶段、迭代数、耗时、最佳步等),开始新一轮可视化
        self._begin_think()
        self.think.total = self.iterations
        timer = MoveTimer(self.time_limit)
        timer.start()

        # ---- 1. 强制预检:能赢先赢,该挡必挡 ----
        # 这一步不消耗搜索预算,直接用规则 / 棋型判断给出确定结论,
        # 既保证战术正确性,也避免 MCTS 在必胜/必败局面上浪费迭代。
        quick_move = self._forced_move(board)
        if quick_move is not None:
            self.think.phase = "强制预检"
            self.think.best_move = quick_move
            self.think.done = 1
            self._emit(on_progress)
            self.think.finish()
            return quick_move

        # ---- 2. 主搜索循环:四阶段迭代 ----
        # 根节点的 player 参数用 board.current_player,即「本节点将要落子的一方」。
        # state 传入副本,后续所有扩展 / 模拟都不会影响真实棋盘。
        root = _MCTSNode(board.copy(), None, None, board.current_player)
        iterations = 0
        # 进度推送间隔:总迭代的 2%(至少 5 次、至多 200 次)推送一次可视化,
        # 避免每迭代都回调导致界面重绘开销过大。
        emit_interval = max(5, min(200, self.iterations // 50))

        while iterations < self.iterations and not timer.timeout:
            node = self._tree_policy(root)          # 选择 + 扩展
            outcome = self._rollout(node.state)     # 0~1 的本方胜率估计
            self._backpropagate(node, outcome)      # 回传统计
            iterations += 1

            # 定期推送思考进度:迭代数、耗时、Top 候选胜率
            if iterations % emit_interval == 0:
                self.think.done = iterations
                self.think.elapsed = timer.elapsed()
                self.think.phase = f"MCTS 模拟中 · {iterations}/{self.iterations}"
                self._update_top_moves(root)
                self._emit(on_progress)

        # ---- 3. 最终选步 ----
        # 极端情况:一次迭代都没能扩展出子节点(例如预算瞬间耗尽),
        # 退回到候选列表第一步,保证始终返回合法走法。
        if not root.children:
            self.think.finish()
            return legal[0]

        best_child = self._select_best_child(root)
        self.think.best_move = best_child.move
        self.think.best_value = best_child.winrate
        self.think.done = iterations
        self.think.elapsed = timer.elapsed()
        self._update_top_moves(root)
        self.think.phase = "完成搜索"
        self._emit(on_progress)

        log_debug(f"{self.label} MCTS 完成 {iterations} 次迭代,"
                  f"耗时 {timer.elapsed():.2f}s,选中 {best_child.move}"
                  f"(胜率 {best_child.winrate:.1%})")
        self.think.finish()
        return best_child.move

    # ==================== 强制预检(搜索前的战术兜底) ====================

    def _forced_move(self, board) -> Optional[Tuple[int, int]]:
        """
        五子棋四层战术预检，统一复用 ai.candidates.gomoku_forced_move。

        确定性结论放在 MCTS 之前：模拟带随机性，可能被噪声带偏必胜 / 必防；
        第四层额外覆盖跳三 1101 / 1011 补中间空位直接成活四的强制堵点。
        """
        result = gomoku_forced_move(board, self.player)
        if result is not None:
            move, note = result
            self.think.note = note
            return move
        return None

    # ==================== 第一阶段:选择 + 第二阶段:扩展 ====================

    def _tree_policy(self, node: _MCTSNode) -> _MCTSNode:
        """
        树内策略:沿 UCT 向下选择,遇到可扩展节点即扩展,直到抵达终局或新叶子。

        循环逻辑:
            - 当前节点还有未尝试走法 → 立即扩展一手,返回新子节点(第二阶段);
            - 当前节点已完全展开     → 按 UCT 选出最优子节点,继续向下(第一阶段);
            - 走到终局节点           → 直接返回该节点,交给 _rollout 读取结果。

        返回的节点就是本轮「模拟」的起点。
        """
        while not node.state.game_over:
            if not node.fully_expanded:
                return self._expand(node)
            node = node.best_child_by_uct()
        return node

    def _expand(self, node: _MCTSNode) -> _MCTSNode:
        """
        扩展:从未尝试走法中取出一手,生成子节点并挂到父节点下。

        实现细节:
            - untried_moves 在节点构造时已按启发式排序(高分在前、防守点前置),
              这里用 pop() 从列表尾部取出,逐步消耗候选列表;
            - 子节点的局面通过 state.copy() 得到,apply_move 只作用于副本,
              不会污染父节点或真实棋盘;
            - 子节点的 player 取 child_state.current_player,即「下一步该谁走」。
        """
        move = node.untried_moves.pop()
        child_state = node.state.copy()
        child_state.apply_move(move)
        child = _MCTSNode(child_state, node, move, child_state.current_player)
        node.children.append(child)
        return child

    # ==================== 第三阶段:模拟(Rollout) ====================

    def _rollout(self, state) -> float:
        """
        混合策略模拟(返回 0~1 的己方胜率估计)。

        为什么不是「纯随机走到底」:
            - 五子棋分支因子大,纯随机模拟到终局往往由「谁先碰巧凑成五」
              决定,噪声极大;而且「堵活三」这种防守价值在随机胜负统计中
              会被淹没甚至反转。
            - 因此五子棋只模拟固定步数(_ROLLOUT_STEPS),期间用战术贪婪
              保证双方都有基本威胁意识;未分胜负时改用棋型评估,把
              「堵完活三后局面变优」直接折算成胜率。

        黑白棋则模拟至终局,按真实胜负返回 0 / 0.5 / 1。

        返回值的含义始终是「本方(self.player)视角的胜率」。
        """
        sim = state.copy()
        kind = type(sim).__name__
        max_steps = sim.size * sim.size
        steps = 0

        while not sim.game_over and steps < max_steps:
            if kind == "GomokuBoard" and steps >= _ROLLOUT_STEPS:
                break  # 五子棋短模拟到步数即停,交给评估打分
            legal = sim.get_legal_moves()
            if not legal:
                break  # 无合法步可走,按当前局面结束模拟

            # 以一定概率走启发式步,否则纯随机(保留探索多样性)
            move = None
            if random.random() < _HEURISTIC_ROLLOUT_PROB:
                move = self._heuristic_rollout_move(sim, legal)
            if move is None:
                move = random.choice(legal)
            sim.apply_move(move)
            steps += 1

        # 情况 A:模拟走到终局 —— 直接按真实胜负给分
        if sim.game_over:
            if sim.winner == self.player:
                return 1.0
            if sim.winner == DRAW or sim.winner == EMPTY:
                return 0.5
            return 0.0

        # 情况 B:未终局 —— 己方视角评估分经 tanh 平滑映射到 0.05~0.95
        score = evaluate(sim, self.player)
        return 0.5 + 0.45 * math.tanh(score / _EVAL_SCALE)

    def _heuristic_rollout_move(self, sim, legal: List[Tuple[int, int]]
                                ) -> Optional[Tuple[int, int]]:
        """
        启发式模拟选步(不保证每次都有结果,返回 None 时回退纯随机):

        - 五子棋:先做战术贪婪(成五→堵五→成四→堵四),无战术要点时
          在已有棋子邻域内随机落子,避免模拟把棋子下到无关的空旷区域;
        - 黑白棋:按位置权重表加权随机,角 / 边更常被抢到,中心次之;
        - 其它棋种:只做邻域优先,最终可能返回 None 交由随机兜底。

        注意:这里的「战术贪婪」只影响模拟质量,不改变真实对局规则。
        """
        kind = type(sim).__name__

        if kind == "OthelloBoard":
            # 权重可能为负(例如角旁的危险位),统一平移到非负再做加权随机
            weights = [_OTHELLO_WEIGHTS[r][c] for r, c in legal]
            min_w = min(weights)
            shifted = [w - min_w + 1 for w in weights]
            return random.choices(legal, weights=shifted)[0]

        if kind == "GomokuBoard":
            # 战术贪婪:让模拟双方都具备基本威胁意识,
            # 使「不堵活三 → 对手活四 → 必败」能在统计中被真实体现
            tactical = self._tactical_move(sim, legal)
            if tactical is not None:
                return tactical

        # 其它棋种(五子棋兜底 / 围棋):邻域候选优先
        near = [m for m in legal if is_near_stone(sim, m)]
        if near:
            return random.choice(near)
        return None

    def _tactical_move(self, sim, legal: List[Tuple[int, int]]
                       ) -> Optional[Tuple[int, int]]:
        """
        五子棋战术贪婪选步(五级优先级,返回 None 表示无战术要点):

        1. 己方落子即成五 → 直接取胜;
        2. 对手落子即成五 → 必须堵(能赢先赢,该挡必挡);
        3. 己方落子成四(活四 / 冲四)→ 制造必胜威胁;
        4. 对手落子成四 → 抢占其威胁点防守;
        5. 无要点返回 None,交回随机选步。

        与 Alpha-Beta / MCTS 的「预检」不同,这里面对的是模拟过程中的
        任意局面,双方都可能轮到走,因此按 sim.current_player 动态判断敌我。
        """
        me = sim.current_player
        opp = sim.opponent(me)

        # 1. 自己的成五点
        for m in legal:
            if self._line_after(sim, m, me) >= 5:
                return m
        # 2. 对手的成五点(必须堵)
        for m in legal:
            if self._line_after(sim, m, opp) >= 5:
                return m
        # 3. 自己的成四点(活四 / 冲四,制造威胁)
        for m in legal:
            if self._line_after(sim, m, me) >= 4:
                return m
        # 4. 对手的成四点(抢占防守)
        for m in legal:
            if self._line_after(sim, m, opp) >= 4:
                return m
        return None

    @staticmethod
    def _line_after(sim, move: Tuple[int, int], player: int) -> int:
        """
        试探性计算:若 player 在 move 落子,四个方向中最长的连子数是多少。

        实现方式是在真实棋盘对象上「临时落子 → 调用规则层统计 → 立即清空」,
        不经过 apply_move,因此不会触发回合切换、胜负判定或历史记录。
        """
        r, c = move
        sim.board[r][c] = player
        best = sim._count_line(r, c, player)
        sim.board[r][c] = EMPTY
        return best

    # ==================== 第四阶段:回传 ====================

    def _backpropagate(self, node: _MCTSNode, outcome: float) -> None:
        """
        把模拟结果沿父链向上回传,更新各节点访问次数与胜场统计。

        视角约定:全树统一按本方(根节点,即本 AI 一方)视角记录胜率,
        outcome 即 0~1 的本方胜率估计。这样 selection 阶段对所有子节点
        直接取 max(winrate) 即为最优,避免「子节点胜率 = 对方胜率」
        导致的选择方向反转。

        参数:
            node:    本轮模拟的起点(新扩展的叶子节点);
            outcome: 本轮模拟得到的一方胜率 (0 输 / 0.5 平 / 1 赢,
                     或评估映射出的连续值)。
        """
        while node is not None:
            node.visits += 1
            node.wins += outcome
            node = node.parent # type: ignore

    # ==================== 最终选步与可视化辅助 ====================

    def _select_best_child(self, root: _MCTSNode) -> _MCTSNode:
        """
        最终选步策略:

        1. 先算一个「最小样本量」:根访问数 / 子节点数 / 3(至少 3 次),
           即平均每个子节点应当被访问的次数量级;
        2. 只在访问次数达到该样本量的子节点中挑胜率最高者 —— 访问少的
           节点胜率方差大, 容易出现「1 次访问 1 次胜利 = 100%」的假象;
        3. 若所有子节点都没达到样本量(迭代预算很小),退回访问次数最多者,
           因为它至少统计更稳定。

        返回:根节点下要实际落子的子节点。
        """
        min_samples = max(3, root.visits // max(1, len(root.children)) // 3)
        qualified = [c for c in root.children if c.visits >= min_samples]
        pool = qualified or root.children
        return max(pool, key=lambda c: (c.winrate, c.visits))

    def _update_top_moves(self, root: _MCTSNode) -> None:
        """
        把根节点下「访问次数 Top3」的走法及其胜率写入思考状态,
        供界面在棋盘上以彩色圆环高亮,并在侧栏列出候选。

        这里按访问次数排序而不是胜率:访问次数代表搜索实际投入的预算,
        更能反映算法「认真考虑过」的候选;胜率只作为辅助信息展示。
        """
        ranked = sorted(root.children, key=lambda c: c.visits, reverse=True)[:3]
        self.think.top_moves = [ # type: ignore
            (c.move, c.visits, c.winrate) for c in ranked
        ]
