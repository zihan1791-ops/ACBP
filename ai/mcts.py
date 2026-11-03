# -*- coding: utf-8 -*-
"""
蒙特卡洛树搜索（Monte Carlo Tree Search, MCTS）—— 强化版。

算法四阶段：
1. 选择（Selection）：从根节点沿 UCT（置信上界）公式逐层向下，
   优先选择「胜率高且尝试次数少」的子节点；
2. 扩展（Expansion）：按启发式先验排序候选走法，优先展开高价值分支；
3. 模拟（Rollout）：五子棋短模拟（战术贪婪成五→堵五→成四→堵四）后
   用局面评估打分，黑白棋按位置权重加权随机模拟至终局，比纯随机更准；
4. 回传（Backpropagation）：把模拟胜负沿路径更新各节点访问次数与胜率。

相比基础版的强化：
- 候选裁剪 + 启发式先验排序（搜索集中在关键邻域）；
- 强制预检：能赢先赢、该挡必挡；
- 最终选步：优先「访问足够多且胜率最高」的走法，避免纯访问数被噪声带偏；
- 思考过程通过 ThinkState + on_progress 回调实时推送（迭代进度、Top 候选、胜率）。

本实现与具体棋种解耦：只要棋盘实现了 core.base_board 的统一接口即可使用。
"""

import math
import random
from typing import Optional, Tuple, List

from .base_ai import BaseAI
from .candidates import (
    candidate_moves, gomoku_winning_moves, gomoku_attack_points,
    gomoku_defense_points, sort_moves_by_heuristic, is_near_stone,
)
from .evaluator import evaluate, _OTHELLO_WEIGHTS
from core.base_board import DRAW, EMPTY
from utils.helpers import MoveTimer
from utils.logger import log_debug

# UCT 探索常数 C：权衡「利用已知优势」与「探索未知分支」。
# 五子棋候选点多（40~80）、rollout 噪声大，经典 sqrt(2) 会让访问被
# 均匀打散、胜率无法分辨；取 0.25 强利用，让高胜率分支被集中访问。
_UCT_EXPLORE = 0.25

# 启发式 rollout 的使用概率（其余比例纯随机，保持一定探索）
_HEURISTIC_ROLLOUT_PROB = 0.7

# 五子棋短模拟步数上限：超过后改用局面评估（见 _rollout 说明）
_ROLLOUT_STEPS = 12

# 局面评估分 → 胜率的 tanh 缩放系数（棋型分典型量级 ~±200）
_EVAL_SCALE = 120.0


class _MCTSNode:
    """MCTS 搜索树节点。"""

    def __init__(self, state, parent: Optional["_MCTSNode"],
                 move: Optional[Tuple[int, int]], player: int) -> None:
        self.state = state                                  # 节点代表的棋盘局面副本
        self.parent = parent                                # 父节点引用
        self.move = move                                    # 走到本节点的那一步棋
        self.player = player                                # 本节点局面中将要落子的玩家
        self.children: List[_MCTSNode] = []                 # 已扩展子节点
        # 候选走法：邻域裁剪 + 启发式排序（高价值在前）
        self.untried_moves: List[Tuple[int, int]] = candidate_moves(state)
        if len(self.untried_moves) > 1:
            self.untried_moves = sort_moves_by_heuristic(
                state, self.untried_moves, player)
            # 五子棋：对手活三 / 冲三的防守点前置，优先扩展与访问
            if type(state).__name__ == "GomokuBoard":
                defs = gomoku_defense_points(state, player)
                if defs:
                    self.untried_moves = (
                        [m for m in defs if m in self.untried_moves]
                        + [m for m in self.untried_moves if m not in defs]
                    )
        self.visits = 0                                     # 节点被访问次数
        self.wins = 0.0                                     # 本节点玩家视角累计胜场（平局计 0.5）

    @property
    def fully_expanded(self) -> bool:
        """是否所有候选走法都已扩展完毕。"""
        return not self.untried_moves

    @property
    def winrate(self) -> float:
        """平均胜率（访问次数为 0 时返回 0）。"""
        return self.wins / self.visits if self.visits else 0.0

    def uct_score(self, parent_visits: int) -> float:
        """计算当前子节点的 UCT 得分：利用项 + 探索项。"""
        exploit = self.winrate
        explore = _UCT_EXPLORE * math.sqrt(
            math.log(parent_visits) / self.visits)                         # 探索强度
        return exploit + explore

    def best_child_by_uct(self) -> "_MCTSNode":
        """按 UCT 公式选出最优子节点。"""
        return max(self.children, key=lambda child: child.uct_score(self.visits))


class MCTSAI(BaseAI):
    """蒙特卡洛树搜索 AI（启发式强化版）。"""

    name = "mcts"
    display_name = "MCTS"

    def __init__(self, player: int, config) -> None:
        super().__init__(player, config)
        # 每步最大迭代次数 / 最大思考秒数，二者先到即停
        self.iterations = max(1, int(config.mcts_iterations))
        self.time_limit = float(config.mcts_time)

    # -------------------- 对外接口 --------------------

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        """执行一轮 MCTS 迭代，返回根节点下最优走法。"""
        legal = candidate_moves(board)
        if not legal:
            return None

        self._begin_think()
        self.think.total = self.iterations
        timer = MoveTimer(self.time_limit)
        timer.start()

        # ---- 1. 强制预检：能赢先赢，该挡必挡 ----
        quick_move = self._forced_move(board)
        if quick_move is not None:
            self.think.phase = "强制预检"
            self.think.best_move = quick_move
            self.think.done = 1
            self._emit(on_progress)
            self.think.finish()
            return quick_move

        # ---- 2. 主搜索循环 ----
        root = _MCTSNode(board.copy(), None, None, board.current_player)
        iterations = 0
        # 进度推送间隔：总迭代的 2%（至少 5 次、至多 200 次）推送一次可视化
        emit_interval = max(5, min(200, self.iterations // 50))

        while iterations < self.iterations and not timer.timeout:
            node = self._tree_policy(root)          # 选择 + 扩展
            outcome = self._rollout(node.state)     # 0~1 的本方胜率估计
            self._backpropagate(node, outcome)      # 回传统计
            iterations += 1

            # 定期推送思考进度：迭代数、耗时、Top 候选胜率
            if iterations % emit_interval == 0:
                self.think.done = iterations
                self.think.elapsed = timer.elapsed()
                self.think.phase = f"MCTS 模拟中 · {iterations}/{self.iterations}"
                self._update_top_moves(root)
                self._emit(on_progress)

        # ---- 3. 最终选步 ----
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

        log_debug(f"{self.label} MCTS 完成 {iterations} 次迭代，"
                  f"耗时 {timer.elapsed():.2f}s，选中 {best_child.move}"
                  f"（胜率 {best_child.winrate:.1%}）")
        self.think.finish()
        return best_child.move

    # -------------------- 强制预检 --------------------

    def _forced_move(self, board) -> Optional[Tuple[int, int]]:
        """五子棋强制进攻 / 防守预检（同 Alpha-Beta，保证两种算法行为一致）。"""
        if type(board).__name__ != "GomokuBoard":
            return None

        opponent = board.opponent(self.player)
        my_wins = gomoku_winning_moves(board, self.player)
        if my_wins:
            self.think.note = "发现制胜点，直接成五"
            return my_wins[0]

        opp_wins = gomoku_winning_moves(board, opponent)
        if opp_wins:
            self.think.note = f"检测到对手冲四（{len(opp_wins)} 处），强制防守"
            return opp_wins[0]

        attacks = gomoku_attack_points(board, self.player)
        if attacks:
            self.think.note = "己方活三成四，抢先制造活四"
            return attacks[0]

        defs = gomoku_defense_points(board, self.player)
        if defs:
            self.think.note = f"检测到对手活三（{len(defs)} 处），堵端防守"
            return defs[0]
        return None

    # -------------------- MCTS 四阶段内部实现 --------------------

    def _tree_policy(self, node: _MCTSNode) -> _MCTSNode:
        """
        树内策略：沿 UCT 向下选择，遇到可扩展节点即扩展，直到抵达终局或新叶子。
        """
        while not node.state.game_over:
            if not node.fully_expanded:
                return self._expand(node)
            node = node.best_child_by_uct()
        return node

    def _expand(self, node: _MCTSNode) -> _MCTSNode:
        """从未尝试走法中取出（启发式排序后最优先的）一步，生成子节点。"""
        move = node.untried_moves.pop()
        child_state = node.state.copy()
        child_state.apply_move(move)
        child = _MCTSNode(child_state, node, move, child_state.current_player)
        node.children.append(child)
        return child

    def _rollout(self, state) -> float:
        """
        混合策略模拟（返回 0~1 的己方胜率估计）。

        - 五子棋：短模拟（最多 _ROLLOUT_STEPS 步，战术贪婪 + 随机）后若未终局，
          改用棋型评估函数打分并映射为胜率。原因是五子棋长 rollout 到终局会被
          「随机凑五」噪声主导，战术防守（如堵活三）的价值在纯胜负统计中会被
          淹没甚至反转；短模拟 + 评估能让「堵完活三局面变优」直接被统计到。
        - 黑白棋：模拟至终局按胜负返回 0 / 0.5 / 1。
        """
        sim = state.copy()
        kind = type(sim).__name__
        max_steps = sim.size * sim.size
        steps = 0

        while not sim.game_over and steps < max_steps:
            if kind == "GomokuBoard" and steps >= _ROLLOUT_STEPS:
                break  # 五子棋短模拟到步数即停，交给评估打分
            legal = sim.get_legal_moves()
            if not legal:
                break  # 无合法步可走，按当前局面结束模拟

            move = None
            if random.random() < _HEURISTIC_ROLLOUT_PROB:
                move = self._heuristic_rollout_move(sim, legal)
            if move is None:
                move = random.choice(legal)
            sim.apply_move(move)
            steps += 1

        if sim.game_over:
            if sim.winner == self.player:
                return 1.0
            if sim.winner == DRAW or sim.winner == EMPTY:
                return 0.5
            return 0.0

        # 未终局：己方视角评估分 → 胜率估计（tanh 平滑映射到 0.05~0.95）
        score = evaluate(sim, self.player)
        return 0.5 + 0.45 * math.tanh(score / _EVAL_SCALE)

    def _heuristic_rollout_move(self, sim, legal: List[Tuple[int, int]]
                                ) -> Optional[Tuple[int, int]]:
        """
        启发式模拟选步（不保证每次都有结果，返回 None 时回退纯随机）：
        - 五子棋：先做战术贪婪（成五→堵五→成四→堵四），再落邻域；
        - 黑白棋：按位置权重表加权随机，角 / 边更常被抢到。
        """
        kind = type(sim).__name__

        if kind == "OthelloBoard":
            weights = [_OTHELLO_WEIGHTS[r][c] for r, c in legal]
            # 权重可能为负，统一平移到非负再做加权随机
            min_w = min(weights)
            shifted = [w - min_w + 1 for w in weights]
            return random.choices(legal, weights=shifted)[0]

        if kind == "GomokuBoard":
            # 战术贪婪：让模拟双方都具备基本威胁意识，
            # 使「不堵活三 → 对手活四 → 必败」能在统计中被真实体现
            tactical = self._tactical_move(sim, legal)
            if tactical is not None:
                return tactical

        # 其它棋种（五子棋兜底 / 围棋）：邻域候选优先
        near = [m for m in legal if is_near_stone(sim, m)]
        if near:
            return random.choice(near)
        return None

    def _tactical_move(self, sim, legal: List[Tuple[int, int]]
                       ) -> Optional[Tuple[int, int]]:
        """
        五子棋战术贪婪选步（五级优先级，返回 None 表示无战术要点）：
        1. 己方落子即成五 → 直接取胜；
        2. 对手落子即成五 → 必须堵（能赢先赢，该挡必挡）；
        3. 己方落子成四（活四 / 冲四）→ 制造必胜威胁；
        4. 对手落子成四 → 抢占其威胁点防守；
        5. 无要点返回 None，交回随机选步。
        """
        me = sim.current_player
        opp = sim.opponent(me)

        for m in legal:
            if self._line_after(sim, m, me) >= 5:
                return m
        for m in legal:
            if self._line_after(sim, m, opp) >= 5:
                return m
        for m in legal:
            if self._line_after(sim, m, me) >= 4:
                return m
        for m in legal:
            if self._line_after(sim, m, opp) >= 4:
                return m
        return None

    @staticmethod
    def _line_after(sim, move: Tuple[int, int], player: int) -> int:
        """临时在 (move) 放一枚 player 棋子，返回四个方向中最长连子数。"""
        r, c = move
        sim.board[r][c] = player
        best = sim._count_line(r, c, player)
        sim.board[r][c] = EMPTY
        return best

    def _backpropagate(self, node: _MCTSNode, outcome: float) -> None:
        """
        把模拟结果沿父链向上回传，更新各节点访问次数与胜场统计。

        视角约定：全树统一按本方（根节点，即本 AI 一方）视角记录胜率，
        outcome 即 0~1 的本方胜率估计。这样 selection 阶段对所有子节点
        直接取 max(winrate) 即为最优，避免「子节点胜率 = 对方胜率」
        导致的选择方向反转。
        """
        while node is not None:
            node.visits += 1
            node.wins += outcome
            node = node.parent

    # -------------------- 最终选步与可视化辅助 --------------------

    def _select_best_child(self, root: _MCTSNode) -> _MCTSNode:
        """
        最终选步策略：
        优先在「访问次数达到最小样本量」的子节点中挑胜率最高者；
        若都未达到样本量，退回访问次数最多的子节点（统计更稳）。
        """
        min_samples = max(3, root.visits // max(1, len(root.children)) // 3)
        qualified = [c for c in root.children if c.visits >= min_samples]
        pool = qualified or root.children
        return max(pool, key=lambda c: (c.winrate, c.visits))

    def _update_top_moves(self, root: _MCTSNode) -> None:
        """把根节点下访问次数 Top3 走法及其胜率写入思考状态，供界面高亮。"""
        ranked = sorted(root.children, key=lambda c: c.visits, reverse=True)[:3]
        self.think.top_moves = [
            (c.move, c.visits, c.winrate) for c in ranked
        ]
