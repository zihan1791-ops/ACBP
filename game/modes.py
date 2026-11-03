# -*- coding: utf-8 -*-
"""
对局模式工厂。

根据「棋种 + 对局模式 + 双方算法」组装棋盘、玩家与 GameController：
- human_vs_ai     人机大战：一方人类、一方 AI；
- ai_vs_ai        算法 PK：双方均为 AI，可分别绑定不同算法；
- human_vs_human  人人对战：双方均为人类。

配置不完整时在此处做归一化兜底，保证主程序可以稳定开局。
"""

from typing import Optional

from core import BOARD_CLASSES
from core.base_board import BLACK, WHITE
from config import GAME_DEFAULTS
from ai.factory import create_ai
from game.player import Player
from game.controller import GameController
from utils.logger import log_warn


def build_players(mode: str, p1_ai_name: Optional[str],
                 p2_ai_name: Optional[str], config
                 ) -> tuple[Player, Player]:
    """
    按对局模式归一化双方算法配置并构造玩家对象。

    参数：
        mode:        对局模式；
        p1_ai_name:  先手（黑方）算法标识，None 表示人类；
        p2_ai_name:  后手（白方）算法标识，None 表示人类；
        config:      全局运行配置。
    返回：
        (先手玩家, 后手玩家)。
    """
    # ---- 人人对战：强制双方为人类，忽略任何算法配置 ----
    if mode == "human_vs_human":
        p1_ai_name = None
        p2_ai_name = None

    # ---- 算法 PK：缺失算法时退回随机基线，保证双方都是 AI ----
    elif mode == "ai_vs_ai":
        if p1_ai_name is None:
            p1_ai_name = "random"
        if p2_ai_name is None:
            p2_ai_name = "random"

    # ---- 人机大战：必须恰好一方为人类、一方为 AI，配置冲突时自动归一化 ----
    elif mode == "human_vs_ai":
        if p1_ai_name is None and p2_ai_name is None:
            # 两边都未指定算法：默认人类先手、MCTS 后手
            p2_ai_name = "mcts"
        elif p1_ai_name is not None and p2_ai_name is not None:
            # 两边都配置了算法：按人机模式视为后手为人类
            log_warn("人机大战检测到双方均配置 AI，已将后手切换为人类玩家")
            p2_ai_name = None
        # 其余情况保持现状：p1 None 即人类先手；p2 None 即人类后手

    ai1 = create_ai(p1_ai_name, BLACK, config)
    ai2 = create_ai(p2_ai_name, WHITE, config)

    player1 = Player(BLACK, "黑方", ai1)
    player2 = Player(WHITE, "白方", ai2)
    return player1, player2


def create_game(game_kind: str, mode: str,
                p1_ai_name: Optional[str], p2_ai_name: Optional[str],
                config, board_size: Optional[int] = None) -> GameController:
    """
    工厂方法：创建一局完整对局控制器。

    参数：
        game_kind:   棋种标识 gomoku / othello / go；
        mode:        对局模式；
        p1_ai_name:  先手算法标识；
        p2_ai_name:  后手算法标识；
        config:      全局运行配置；
        board_size:  显式棋盘尺寸；None 时依次取 config.board_size、棋种默认值。
    """
    if game_kind not in BOARD_CLASSES:
        raise ValueError(f"未知棋种：{game_kind}")

    board_cls = BOARD_CLASSES[game_kind]
    size = board_size or config.board_size or GAME_DEFAULTS[game_kind]["board_size"]
    board = board_cls(size)

    player1, player2 = build_players(mode, p1_ai_name, p2_ai_name, config)
    return GameController(board, player1, player2, config, game_kind, size)


def _role_to_player(role: Optional[dict], player_id: int, config) -> Player:
    """把棋谱中的角色信息还原为玩家对象（AI 按记录算法创建，人类则无 AI）。"""
    if role and role.get("type") == "ai":
        ai = create_ai(role.get("ai"), player_id, config)
        return Player(player_id, "黑方" if player_id == BLACK else "白方", ai)
    return Player(player_id, "黑方" if player_id == BLACK else "白方", None)


def _record_ai(role: Optional[dict]) -> Optional[str]:
    """从棋谱角色信息中提取算法名；人类或无角色返回 None。"""
    if role and role.get("type") == "ai":
        return role.get("ai")
    return None


# 哨兵：表示「未显式指定，沿用棋谱记录的角色」
_UNSET = object()


def resume_game_from_record(record: dict, config,
                            step: Optional[int] = None,
                            p1_ai=_UNSET, p2_ai=_UNSET) -> GameController:
    """
    从棋谱回放点恢复对局控制器（「回放到此，继续对弈」）。

    参数：
        record: 棋谱 JSON（game / board_size / players / moves 等字段）；
        config: 全局运行配置；
        step:   要恢复到的已下步数；None 表示恢复到棋谱末尾；
        p1_ai:  黑方角色覆盖：算法名或 None（人类）；
                不传（默认）时按棋谱记录还原；
        p2_ai:  白方角色覆盖：算法名或 None（人类）；
                不传（默认）时按棋谱记录还原。
    返回：
        棋盘已恢复到 step 手、双方角色按指定（或按棋谱）还原的对局控制器。
    """
    game_kind = record["game"]
    if game_kind not in BOARD_CLASSES:
        raise ValueError(f"未知棋种：{game_kind}")

    size = record.get("board_size") or GAME_DEFAULTS[game_kind]["board_size"]
    board = BOARD_CLASSES[game_kind](size)

    moves = record.get("moves", [])
    count = len(moves) if step is None else max(0, min(step, len(moves)))
    for mv in moves[:count]:
        board.apply_move(tuple(mv["move"]))

    players = record.get("players", {})
    black_ai = _record_ai(players.get("black"))
    white_ai = _record_ai(players.get("white"))
    p1_name = black_ai if p1_ai is _UNSET else p1_ai
    p2_name = white_ai if p2_ai is _UNSET else p2_ai
    player1 = _role_to_player({"type": "ai", "ai": p1_name} if p1_name
                              else {"type": "human"}, BLACK, config)
    player2 = _role_to_player({"type": "ai", "ai": p2_name} if p2_name
                              else {"type": "human"}, WHITE, config)
    return GameController(board, player1, player2, config, game_kind, size)
