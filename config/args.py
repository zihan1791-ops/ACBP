# -*- coding: utf-8 -*-
"""
命令行参数解析与配置合并。

参数优先级（高 → 低）：
    命令行显式传入参数  >  config/settings.py 中的全局变量

本模块同时支持两种使用方式：
1. PyCharm 直接调参：修改 settings.py 中的全局变量即可，无需任何命令行；
2. 命令行调参：在启动参数中传入对应选项，覆盖全局变量。
"""

import argparse
import random

from . import settings as S
from .skins import SKIN_IDS
from utils.logger import log_warn


class Config:
    """
    解析后的运行配置对象。

    全部参数以属性方式访问，例如：cfg.game、cfg.mcts_iterations；
    未设置的可选参数在构造阶段已补全为确定值，运行期不会出现 None 歧义。
    """

    def __init__(self, data: dict) -> None:
        self._data = dict(data)

    def __getattr__(self, name: str):
        # 仅在普通属性查找失败时到内部字典中取值
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"配置项不存在：{name}")

    def get(self, key: str, default=None):
        """按 key 安全取值，缺失时返回 default。"""
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        """返回配置字典副本（便于日志打印与调试）。"""
        return dict(self._data)


def _build_parser() -> argparse.ArgumentParser:
    """
    构造命令行参数解析器。

    所有参数默认 None：表示「命令行未传入，沿用 settings.py 全局变量」，
    从而保证「不传命令行 = 完全使用源码全局变量调参」。
    """
    parser = argparse.ArgumentParser(
        description="五子棋 / 黑白棋 / 围棋 / 中国象棋 人机大战与算法 PK 综合对战平台",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # ---- 棋种与对局模式 ----
    parser.add_argument("--game", choices=S.VALID_GAMES, default=None,
                        help="选择棋种：gomoku 五子棋 / othello 黑白棋 / "
                             "go 围棋 / chess 中国象棋")
    parser.add_argument("--mode", choices=S.VALID_MODES, default=None,
                        help="对局模式：human_vs_ai / ai_vs_ai / human_vs_human")
    parser.add_argument("--board-size", type=int, default=None,
                        help="棋盘尺寸（路数/格数），默认取各棋种预设值")

    # ---- 双方 AI 算法 ----
    parser.add_argument("--p1-ai", choices=S.VALID_AIS, default=None,
                        help="先手（黑方）算法：mcts / alphabeta / random / "
                             "iga / de / pso / abc；不传该参数表示人类")
    parser.add_argument("--p2-ai", choices=S.VALID_AIS, default=None,
                        help="后手（白方）算法：mcts / alphabeta / random / "
                             "iga / de / pso / abc；不传该参数表示人类")

    # ---- 双方棋子外观（可选覆盖，默认取 settings.P1_SKIN / P2_SKIN） ----
    parser.add_argument("--p1-skin", choices=SKIN_IDS, default=None,
                        help="先手（黑方）棋子外观：classic / ember / azure / violet")
    parser.add_argument("--p2-skin", choices=SKIN_IDS, default=None,
                        help="后手（白方）棋子外观：classic / ember / azure / violet")

    # ---- AI 搜索参数（统一最大努力预算，命令行仅作显式覆盖） ----
    parser.add_argument("--mcts-iterations", type=int, default=None,
                        help="MCTS 每步最大迭代次数（覆盖全局变量）")
    parser.add_argument("--mcts-time", type=float, default=None,
                        help="MCTS 每步最大思考秒数（覆盖全局变量）")
    parser.add_argument("--ab-depth", type=int, default=None,
                        help="Alpha-Beta 迭代加深最大深度（覆盖全局变量）")
    parser.add_argument("--ab-time", type=float, default=None,
                        help="Alpha-Beta 每步最大思考秒数（覆盖全局变量）")
    parser.add_argument("--evo-population", type=int, default=None,
                        help="群体优化 AI 种群规模（覆盖全局变量）")
    parser.add_argument("--evo-generations", type=int, default=None,
                        help="群体优化 AI 最大进化代数（覆盖全局变量）")
    parser.add_argument("--evo-horizon", type=int, default=None,
                        help="群体优化 AI 单个体推演步数（覆盖全局变量）")
    parser.add_argument("--evo-time", type=float, default=None,
                        help="群体优化 AI 每步最大思考秒数（覆盖全局变量）")
    parser.add_argument("--seed", type=int, default=None,
                        help="随机数种子，填写整数可复现随机过程")

    # ---- 显示与日志 ----
    parser.add_argument("--width", type=int, default=None, help="窗口宽度（像素）")
    parser.add_argument("--height", type=int, default=None, help="窗口高度（像素）")
    parser.add_argument("--save-records", action="store_true", default=None,
                        help="开启棋谱自动保存（覆盖全局 SAVE_RECORDS）")
    parser.add_argument("--records-dir", default=None,
                        help="棋谱保存目录（覆盖全局 RECORDS_DIR）")
    parser.add_argument("--debug", action="store_true", default=None,
                        help="开启调试日志（命令行开启即覆盖全局 DEBUG）")
    parser.add_argument("--show-log", action="store_true", default=None,
                        help="开启常规日志（命令行开启即覆盖全局 SHOW_LOG）")

    return parser


def load_config(argv=None) -> Config:
    """
    读取 settings.py 全局变量，合并命令行参数并做基础校验，
    返回最终生效的 Config 对象。

    参数：
        argv: 命令行参数列表；传 None 时读取 sys.argv（main 入口直接调用即可）。
    """
    parser = _build_parser()
    args, _unknown = parser.parse_known_args(argv)  # 兼容未知参数，避免 PyCharm 额外参数导致崩溃

    # ---- 1. 以 settings.py 全局变量为基底 ----
    data: dict = {
        "game": S.GAME,
        "mode": S.MODE,
        "first_player": S.FIRST_PLAYER,
        "p1_ai": S.PLAYER1_AI,
        "p2_ai": S.PLAYER2_AI,
        "p1_skin": S.P1_SKIN,
        "p2_skin": S.P2_SKIN,
        "board_size": S.BOARD_SIZE,
        "mcts_iterations": S.MCTS_ITERATIONS,
        "mcts_time": S.MCTS_TIME_LIMIT,
        "ab_depth": S.AB_MAX_DEPTH,
        "ab_time": S.AB_TIME_LIMIT,
        "evo_population": S.EVO_POPULATION,
        "evo_generations": S.EVO_GENERATIONS,
        "evo_horizon": S.EVO_HORIZON,
        "evo_time": S.EVO_TIME_LIMIT,
        "evo_elite": S.EVO_ELITE,
        "evo_stall_limit": S.EVO_STALL_LIMIT,
        "evo_de_f": S.EVO_DE_F,
        "evo_de_cr": S.EVO_DE_CR,
        "evo_abc_limit": S.EVO_ABC_LIMIT,
        "random_seed": S.RANDOM_SEED,
        "window_width": S.WINDOW_WIDTH,
        "window_height": S.WINDOW_HEIGHT,
        "save_records": S.SAVE_RECORDS,
        "records_dir": S.RECORDS_DIR,
        "show_log": S.SHOW_LOG,
        "debug": S.DEBUG,
        "fps": S.FPS,
    }

    # ---- 2. 命令行显式参数覆盖全局变量（值不为 None 才覆盖） ----
    if args.game is not None:
        data["game"] = args.game
    if args.mode is not None:
        data["mode"] = args.mode
    if args.board_size is not None:
        data["board_size"] = args.board_size
    if args.p1_ai is not None:
        data["p1_ai"] = args.p1_ai
    if args.p2_ai is not None:
        data["p2_ai"] = args.p2_ai
    if args.p1_skin is not None:
        data["p1_skin"] = args.p1_skin
    if args.p2_skin is not None:
        data["p2_skin"] = args.p2_skin
    if args.mcts_iterations is not None:
        data["mcts_iterations"] = args.mcts_iterations
    if args.mcts_time is not None:
        data["mcts_time"] = args.mcts_time
    if args.ab_depth is not None:
        data["ab_depth"] = args.ab_depth
    if args.ab_time is not None:
        data["ab_time"] = args.ab_time
    if args.evo_population is not None:
        data["evo_population"] = args.evo_population
    if args.evo_generations is not None:
        data["evo_generations"] = args.evo_generations
    if args.evo_horizon is not None:
        data["evo_horizon"] = args.evo_horizon
    if args.evo_time is not None:
        data["evo_time"] = args.evo_time
    if args.seed is not None:
        data["random_seed"] = args.seed
    if args.width is not None:
        data["window_width"] = args.width
    if args.height is not None:
        data["window_height"] = args.height
    if args.save_records is not None:
        data["save_records"] = args.save_records
    if args.records_dir is not None:
        data["records_dir"] = args.records_dir
    if args.debug is not None:
        data["debug"] = args.debug
    if args.show_log is not None:
        data["show_log"] = args.show_log

    # ---- 3. 棋盘尺寸：未指定时取当前棋种默认值 ----
    if data["game"] is not None:
        defaults = S.GAME_DEFAULTS[data["game"]]
        if data["board_size"] is None:
            data["board_size"] = defaults["board_size"]
        elif data["board_size"] not in defaults["allowed_sizes"]:
            # 尺寸不在允许范围时回退默认，并给出警告
            log_warn(f"棋盘尺寸 {data['board_size']} 不被 {data['game']} 支持，"
                     f"已回退为默认 {defaults['board_size']}")
            data["board_size"] = defaults["board_size"]
    else:
        # 未在配置中指定棋种（将进入主菜单），棋盘尺寸留待选择棋种后解析
        data["board_size"] = None

    # ---- 4. 固定随机种子（可复现随机模拟与随机 AI） ----
    if data["random_seed"] is not None:
        random.seed(data["random_seed"])

    return Config(data)
