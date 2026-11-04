# -*- coding: utf-8 -*-
"""pygame 界面层（ACBP「棋谱刊物」视觉系统）。

分层：设计令牌 theme / 动效 motion / 字体 assets / 氛围 atmosphere /
控件 widgets / 棋盘视图 board_view / 多进程 AI 调度 ai_runner /
场景 main_menu·game_scene·replay_scene / 主循环 app。
除 game/controller.py 新增 apply_ai_move() 外，本层不修改后端既有契约。
"""
