# -*- coding: utf-8 -*-
"""
=====================================================================
全局默认配置 —— PyCharm 调参入口
=====================================================================

【调参方式说明】
1. 本文件中的大写变量即为「全局默认参数」。在 PyCharm 中直接修改本文件
   的变量值，即可在不改动其它源码的前提下完成调参，点击运行即可生效。
2. 命令行参数（见 config/args.py）属于「可选覆盖」：只有在命令行显式传入
   同名参数时，才会覆盖本文件中的全局变量；未传入则继续使用本文件默认值。
3. 若 GAME / MODE 等对局选项保留为 None，程序启动后会先进入图形主菜单，
   由玩家在界面上可视化选择棋种与模式。

【难度说明】
本项目不再划分 easy / medium / hard 难度档位：AI 统一按照下方
「最大努力预算」全力搜索，预算值可在此直接调大或调小。
=====================================================================
"""

from .skins import DEFAULT_SKINS


# ===================== 一、窗口与显示 =====================

# 主窗口逻辑宽 / 高（ui/theme.py 会按系统 DPI 系数换算为物理像素）
# 2560x1600 屏幕 + 150% 缩放下，实际窗口为 2160x1350 物理像素
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900

# 游戏主循环帧率（每秒刷新次数）
FPS = 60


# ===================== 二、对局基本设置 =====================
# 棋种选择：
#   'gomoku' —— 五子棋
#   'othello' —— 黑白棋（奥赛罗）
#   （围棋 go 已暂停启用，见「四、说明」）
#   None     —— 启动后在主菜单可视化选择
GAME = None

# 对局模式：
#   'human_vs_ai'     —— 人机大战（一名人类 vs 一名 AI）
#   'ai_vs_ai'        —— 算法 PK（两个 AI 互相对弈，可分别选择算法）
#   'human_vs_human'  —— 人人对战（本地双人轮流落子）
#   None              —— 启动后在主菜单可视化选择
MODE = None

# 先手方：1 = 黑棋，2 = 白棋。None 表示使用规则默认先手（黑棋先行）
FIRST_PLAYER = 1

# 双方绑定的 AI 算法，可选：
#   'mcts'      —— 蒙特卡洛树搜索
#   'alphabeta' —— Alpha-Beta 剪枝搜索
#   'random'    —— 随机基线 AI（用于流程测试与算法对照）
#   'iga'       —— 改进遗传算法（群体优化选步）
#   'de'        —— 差分进化算法（群体优化选步）
#   'pso'       —— 粒子群优化算法（群体优化选步）
#   'abc'       —— 人工蜂群算法（群体优化选步）
#   None        —— 该方为人类玩家
# 约定：PLAYER1_AI 对应先手（黑方），PLAYER2_AI 对应后手（白方）。
# 例如人机大战且人类先手：PLAYER1_AI = None，PLAYER2_AI = 'mcts'；
# 算法 PK 示例：PLAYER1_AI = 'mcts'，PLAYER2_AI = 'alphabeta'。
PLAYER1_AI = None
PLAYER2_AI = None

# 棋盘尺寸（路数 / 格数）：
#   None —— 使用各棋种默认尺寸（五子棋 15、黑白棋 8）
#   其它整数 —— 显式指定，须落在该棋种允许范围内
BOARD_SIZE = None

# 双方默认棋子外观（可在主菜单里分别更换）：
#   'classic' 经典纯色 / 'ember' 橙发 / 'azure' 蓝发 / 'violet' 紫发
P1_SKIN = DEFAULT_SKINS[1]
P2_SKIN = DEFAULT_SKINS[2]


# ===================== 三、AI 最大努力预算（统一，不分难度） =====================

# MCTS 每一步最大迭代次数（模拟到搜索树的次数上限）
MCTS_ITERATIONS = 5000

# MCTS 每一步最大思考时间（秒）；与迭代次数限制「先到即停」 6
MCTS_TIME_LIMIT = 10.0

# Alpha-Beta 迭代加深的最大搜索深度（向上搜索几层封顶） 6
AB_MAX_DEPTH = 10

# Alpha-Beta 每一步最大思考时间（秒）；超时立即停止加深 6
AB_TIME_LIMIT = 10.0

# 随机数种子：None 表示不固定（每次对局随机不同）；填整数可复现对局
RANDOM_SEED = None


# ===================== 三之二、群体优化 AI 预算 =====================
# 改进遗传 / 差分进化 / 粒子群 / 人工蜂群共用这组预算。
# 个体是长度 evo_horizon 的实数向量，解码成「我走一步 + 对手应一步」的
# 合法推演序列，适应度由局面评估（或终局胜负）给出。

# 种群规模（每代个体数）
EVO_POPULATION = 50

# 最大进化代数；与 EVO_TIME_LIMIT 先到即停
EVO_GENERATIONS = 500

# 单个个体向前推演的我方步数（搜索视野）
EVO_HORIZON = 6

# 每一步最大思考秒数
EVO_TIME_LIMIT = 20.0

# 改进 GA 精英保留数量 / 停滞重启阈值
EVO_ELITE = 2
EVO_STALL_LIMIT = 6

# 差分进化缩放因子 F / 交叉概率 CR
EVO_DE_F = 0.6
EVO_DE_CR = 0.85

# 人工蜂群食物源放弃阈值（连续多少代未改进即重置）
EVO_ABC_LIMIT = 5


# ===================== 四、各棋种默认参数 =====================
# name：界面中显示的中文名称；board_size：默认棋盘尺寸；
# allowed_sizes：该棋种允许选择的尺寸范围（UI 主菜单 / 校验时使用）。
GAME_DEFAULTS = {
    'gomoku': {
        'name': '五子棋',
        'board_size': 15,
        'allowed_sizes': [9, 11, 13, 15],
    },
    'othello': {
        'name': '黑白棋',
        'board_size': 8,
        'allowed_sizes': [8],
    },
    'go': {
        'name': '围棋',
        'board_size': 9,
        'allowed_sizes': [9, 13, 19],
    },
    'chess': {
        'name': '中国象棋',
        'board_size': 10,
        'allowed_sizes': [10],
    },
}

# 当前实际开放给玩家选择的棋种
ACTIVE_GAMES = ['gomoku', 'othello', 'go', 'chess']

# 合法选项集合，供参数校验使用（与对外开放选项保持一致）
VALID_GAMES = ACTIVE_GAMES
VALID_MODES = ['human_vs_ai', 'ai_vs_ai', 'human_vs_human']
# 'edax' 为黑白棋专用外部引擎（可选）：本体位于 vendor/edax/，缺失时菜单自动隐藏；
# 可用环境变量与深度/超时配置见 ai/othello_ext 模块说明。
VALID_AIS = ['mcts', 'alphabeta', 'random', 'iga', 'de', 'pso', 'abc', 'edax']


# ===================== 五、棋谱与日志 =====================
# True：每局结束自动把棋谱（含双方角色、全部落子、胜负）保存为 JSON 文件
SAVE_RECORDS = True

# 棋谱保存目录（相对项目根目录；可改绝对路径）
RECORDS_DIR = "records"

# True：在控制台打印对局流程、AI 选步与耗时等信息
SHOW_LOG = True

# True：输出更详细的调试信息（搜索节点数、评估分值等）
DEBUG = False
