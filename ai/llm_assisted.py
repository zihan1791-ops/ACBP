# -*- coding: utf-8 -*-
"""
大模型提名 + MCTS 验证（LlmAssistedAI）。

动机（实测结论）：让大模型直接落子，它有棋理常识但缺少搜索与强制战术校验，
面对 MCTS 会连续漏防对手活三、被单向活四击败；而 MCTS 的候选裁剪与随机
模拟又不理解「棋理」。本类把两者的长处接起来，分两步走：

1. 提名（LlmAI.propose）：把局面编码成文本棋盘 + 战术要点（成五 / 堵五 /
   活四 / 堵活三），请大模型给出至多 k 个候选分支（LLM_PROPOSALS，默认 3）；
2. 验证（MCTSAI.set_restrict）：MCTS 把根节点分支限定在这 k 个点内，用
   完整迭代做模拟胜负验证，选出真正占优的一步。

兜底与不变量：
- 模型调用失败或候选不足时，LlmAI.propose 内部用启发式候选补齐；
- MCTS 的强制预检（能赢先赢、该挡必挡）在搜索前执行，命中即直接落子，
  不受提名限制影响，保证战术正确性优先于模型偏好；
- 候选点始终经过棋盘合法性与 MCTS 根节点过滤，不存在非法落子。
"""

import time
from typing import List, Optional, Tuple

from .base_ai import BaseAI
from .llm_ai import LlmAI
from .mcts import MCTSAI
from utils.logger import log_info


class LlmAssistedAI(BaseAI):
    """大模型负责提名候选，MCTS 负责搜索验证的混合棋手。"""

    name = "llm_mcts"
    display_name = "大模型+MCTS"

    def __init__(self, player: int, config) -> None:
        super().__init__(player, config)
        # 两个子棋手共用同一 config 与 player；各自持有独立的 ThinkState
        self.llm = LlmAI(player, config)
        self.mcts = MCTSAI(player, config)
        # 每步请大模型提名的候选数（1 等价于纯大模型，太大则会稀释搜索预算）
        self.proposals = max(1, int(getattr(config, "llm_proposals", 3)))

    @property
    def model(self) -> str:
        """透传所调用的大模型名（棋谱记录 / 界面展示用）。"""
        return self.llm.model

    # -------------------- 对外接口 --------------------

    def select_move(self, board, on_progress=None) -> Optional[Tuple[int, int]]:
        """先请大模型提名候选，再让 MCTS 在候选内搜索验证。"""
        legal = board.get_legal_moves()
        if not legal:
            return None

        self._begin_think()
        self.think.phase = f"大模型提名 {self.proposals} 个候选"
        self.think.note = "请大模型挑选候选分支…"
        self._emit(on_progress)

        start = time.time()
        # 提名阶段同步执行（单步约 1 秒）；不转发进度回调，避免与外层
        # ThinkState 交替刷新导致界面文字跳动
        moves: List[Tuple[int, int]] = self.llm.propose(
            board, self.proposals, on_progress=None)
        if not moves:
            moves = [legal[0]]

        self.think.elapsed = time.time() - start
        self.think.note = f"大模型提名：{moves}，交给 MCTS 验证"
        self._emit(on_progress)

        # 验证阶段：根节点分支限定为提名点；MCTS 的进度镜像到本棋手的
        # ThinkState（界面读的是外层 think，不镜像则进度条停在提名阶段）
        def relay(state) -> None:
            """把 MCTS 的实时搜索进度同步到外层思考状态并推送给界面。"""
            mine = self.think
            mine.total = state.total
            mine.done = state.done
            mine.phase = state.phase
            mine.note = state.note or f"大模型提名：{moves}"
            mine.elapsed = state.elapsed
            mine.best_move = state.best_move
            mine.best_value = state.best_value
            mine.top_moves = list(state.top_moves)
            self._emit(on_progress)

        self.mcts.set_restrict(moves)
        try:
            move = self.mcts.select_move(board, relay)
        finally:
            self.mcts.set_restrict(None)

        if move is None:
            move = moves[0] if moves[0] in legal else legal[0]

        # 收尾：把搜索统计合并到本对象的 ThinkState，界面显示完整信息
        self.think.phase = f"完成：提名 {len(moves)} 个分支，MCTS 验证"
        self.think.best_move = move
        self.think.best_value = self.mcts.think.best_value
        self.think.top_moves = list(self.mcts.think.top_moves)
        self.think.done = self.mcts.think.done
        self.think.total = self.mcts.think.total
        self.think.elapsed = time.time() - start
        self._emit(on_progress)
        self.think.finish()

        log_info(f"{self.label} 大模型提名 {moves} → MCTS 选中 {move}")
        return move
