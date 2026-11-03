# -*- coding: utf-8 -*-
"""
=====================================================================
统一启动脚本（项目唯一入口）
=====================================================================

【一、PyCharm 调参方式（推荐，源码全局变量覆写）】
    1. 打开 config/settings.py；
    2. 直接修改文件中的大写全局变量（棋种、模式、双方算法、棋盘尺寸、
       MCTS 迭代数 / 思考时长、Alpha-Beta 深度与时长等）；
    3. 在 PyCharm 中右键本文件 → Run 'start'，即可按修改后的参数启动。

【二、命令行参数调参方式（可选覆盖）】
    在终端执行（参数会覆盖 settings.py 中同名全局变量，未传参则沿用全局变量）：

        python start.py --game gomoku --mode human_vs_ai --p2-ai mcts

    不传任何参数启动时，程序进入图形主菜单，可视化选择棋种、模式与算法。

【三、支持棋种与模式】
    棋种：gomoku 五子棋 / othello 黑白棋（围棋已暂停启用）
    模式：human_vs_ai 人机大战 / ai_vs_ai 算法 PK / human_vs_human 人人对战

【四、其它功能】
    1. 棋谱：每局终局自动保存到 records/ 目录（含双方角色与全部落子）；
       主菜单点击「棋谱回放」可单步 / 自动播放复盘；
    2. 高分屏：程序自动按系统 DPI 缩放以物理像素渲染，2K/4K 屏文字清晰；
    3. 棋谱与显示参数可在 settings.py 中调整（SAVE_RECORDS / RECORDS_DIR 等）。
=====================================================================
"""

import sys

from config.args import load_config
from utils.logger import init_logger


def main(argv=None) -> None:
    """程序主入口：解析合并配置 → 初始化日志 → 启动 pygame 应用。"""
    # 1. 读取 settings.py 全局变量，合并命令行覆盖参数，得到最终配置
    cfg = load_config(argv)

    # 2. 初始化日志开关
    init_logger(cfg.show_log, cfg.debug)

    # 3. 延迟导入 pygame 相关模块：保证 --help 等命令行操作无需 pygame 环境
    from ui.app import App

    # 4. 启动应用主循环
    App(cfg).run()


if __name__ == "__main__":
    # sys.argv[1:] 去掉脚本名本身，交给 argparse 解析
    main(sys.argv[1:])
