# -*- coding: utf-8 -*-
"""
全局设计令牌 —— ACBP「棋谱刊物」视觉系统
=====================================================================
设计定调（Direction Lock）
  目的     : 五子棋 / 黑白棋对战平台的桌面界面，面向想看清 AI 演算过程、
             并会回看棋谱的玩家。信息密度偏高，但需支撑长时间对局。
  调性     : 杂志编辑 / 东方纸墨（单一方向，不混搭）。暖纸白底、墨黑文字、
             朱砂红单点强调、宋体大标题、发丝规则线、多栏网格、等宽棋步坐标。
  约束     : pygame 即时模式；1440x900 逻辑像素（2560x1600 屏 @150% 缩放时
             物理 2160x1350）；AI 与界面同线程，进度回调会高频重绘，
             故静态背景与棋盘坐标必须预渲染缓存。
  记忆点   : 「棋谱栏」——右栏用等宽坐标 + 竖直规则线把每一步棋排成
             古籍棋谱的活字列；左侧竖排宋体刊名。
  展示字   : 华文宋体 / 思源宋体（衬线，编辑感），字距 -0.02em
  正文字   : 等线 / 思源黑体；数据用 Cascadia Mono 等宽
  主色     : 暖纸白 #F2EDE3（60%）+ 宣纸面 #FBF8F1（30%）
  强调色   : 朱砂 #B63C25（10%），单屏仅此一个，只给关键动作与激活态

改主题只需改本文件；所有场景、控件、棋盘都只读这里的常量。

分辨率无关：布局统一按 BASE_W x BASE_H 逻辑基准书写，S() 同时乘上
DPI 系数与 CANVAS_SCALE（= 实际窗口宽 / 基准宽）。set_canvas() 在窗口
创建前由 App 调用，命令行 --width/--height 改尺寸时整体等比缩放，不崩版。
"""

from . import dpi

# 进程 DPI 感知 + 读取系统缩放系数（必须在创建 pygame 窗口前生效）
dpi.enable_dpi_awareness()
DPI_SCALE = dpi.dpi_scale()

# 布局逻辑基准：所有场景的坐标都按这个尺寸书写
BASE_W, BASE_H = 1440, 900
CANVAS_SCALE = 1.0


def S(value: int) -> int:
    """把「基准逻辑像素」换算为「物理像素」（含 DPI 与画布缩放）。"""
    return int(value * DPI_SCALE * CANVAS_SCALE)


def window_size(cfg):
    """窗口物理尺寸：只按 DPI 换算，不再乘画布缩放（否则会双重放大）。"""
    return (int(cfg.window_width * DPI_SCALE),
            int(cfg.window_height * DPI_SCALE))


def set_canvas(cfg) -> None:
    """根据实际窗口尺寸重算画布缩放与所有依赖令牌（字号、间距、圆角）。"""
    global CANVAS_SCALE
    CANVAS_SCALE = min(cfg.window_width / BASE_W,
                       cfg.window_height / BASE_H)
    _recompute()


# ===========================================================================
# 1. 语义色板：一个主导表面色 + 一个锐利强调色，60 / 30 / 10 分配
# ===========================================================================
PAPER       = (242, 237, 227)   # #F2EDE3 暖纸白，主导 60%
SURFACE     = (251, 248, 241)   # #FBF8F1 宣纸面板 30%
BOARD_PAPER = (233, 223, 199)   # #E9DFC7 棋墩纸
INK         = (31, 27, 23)      # #1F1B17 墨黑主文字
INK_SOFT    = (110, 101, 90)    # #6E655A 淡墨，所有信息性次级文字（4.90:1）
INK_FAINT   = (167, 156, 140)   # #A79C8C 仅装饰线 / 底纹，不承担任何文字
RULE        = (140, 126, 104)   # #8C7E68 棋盘网格 / 结构线
RULE_LIGHT  = (214, 203, 183)   # #D6CBB7 发丝分隔线
CINNABAR    = (182, 60, 37)     # #B63C25 朱砂，唯一强调色 10%（4.91:1）
CINNABAR_DK = (147, 48, 31)     # #93301F 朱砂深，按压 / 悬停
PAPER_ON_RED = (252, 246, 238)  # 朱砂底上的反白文字

BLACK_STONE      = (35, 31, 27)
WHITE_STONE      = (252, 250, 244)
STONE_SHADOW     = (206, 195, 172)
STONE_HIGHLIGHT  = (90, 82, 72)
STAR_POINT       = (110, 96, 76)

# ---- 旧常量别名：保持既有场景写法可用 ----
BG              = PAPER
PANEL           = SURFACE
PANEL_BORDER    = RULE_LIGHT
BOARD_BG        = BOARD_PAPER
GRID            = RULE
GRID_THIN       = RULE_LIGHT
ACCENT          = CINNABAR
ACCENT_DARK     = CINNABAR_DK
TEXT            = INK
TEXT_LIGHT      = INK_SOFT
TEXT_ON_ACCENT  = PAPER_ON_RED
BUTTON          = SURFACE
BUTTON_HOVER    = (234, 226, 211)
BUTTON_SELECTED = CINNABAR
BLUE            = INK_SOFT      # 单强调色纪律：次级标记用灰墨
WARN            = CINNABAR

# ===========================================================================
# 2. 字阶（1.25 模块化比例）与间距梯度 —— 逻辑值，set_canvas 时换算
# ===========================================================================
_TYPE_LOGIC = {
    "micro":   13,
    "small":   16,
    "body":    19,
    "head":    26,
    "title":   38,
    "display": 56,
    "giant":  150,
}
_SPACE_LOGIC = {1: 4, 2: 8, 3: 16, 4: 24, 5: 40, 6: 64, 7: 96}

TYPE: dict = {}
SPACE: dict = {}
FONT_TITLE = FONT_HEAD = FONT_BODY = FONT_SMALL = 0
PAD = RADIUS = BOARD_MARGIN = 0


def _recompute() -> None:
    """按当前 CANVAS_SCALE 重算字号与间距常量。"""
    global TYPE, SPACE, FONT_TITLE, FONT_HEAD, FONT_BODY, FONT_SMALL
    global PAD, RADIUS, BOARD_MARGIN
    TYPE = {k: S(v) for k, v in _TYPE_LOGIC.items()}
    SPACE = {k: S(v) for k, v in _SPACE_LOGIC.items()}
    FONT_TITLE = TYPE["title"]
    FONT_HEAD = TYPE["head"]
    FONT_BODY = TYPE["body"]
    FONT_SMALL = TYPE["small"]
    PAD = S(24)
    RADIUS = S(4)
    BOARD_MARGIN = S(48)


_recompute()

TRACKING = -0.02     # 展示字字距（相对字号）

# 动效时长（毫秒）：微交互 / 常规过渡 / 场景过渡 / 入场错峰
MOTION = {"micro": 170, "base": 340, "scene": 600, "stagger": 80}
# AI 进度回调重绘限流：同线程计算期间不必每次推送都重画
THINK_REDRAW_MS = 80


# ===========================================================================
# 3. 对比度自检：把「目测够清楚」变成可验证的数值
# ===========================================================================
def _linear(v: float) -> float:
    v /= 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(rgb) -> float:
    r, g, b = rgb[:3]
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(fg, bg) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def blend(a, b, t: float):
    """把颜色 a 按 t(0..1) 向颜色 b 混合，用于入场淡入时不引入额外 Surface。"""
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def qa_report(cfg=None) -> None:
    """启动与设计走查时打印对比度实测值与画布信息。"""
    pairs = [
        ("INK / PAPER",        INK,          PAPER,       4.5),
        ("INK / SURFACE",      INK,          SURFACE,     4.5),
        ("INK_SOFT / PAPER",   INK_SOFT,     PAPER,       4.5),
        ("CINNABAR / PAPER",   CINNABAR,     PAPER,       4.5),
        ("PAPER_ON_RED / RED", PAPER_ON_RED, CINNABAR,    4.5),
        ("INK_FAINT / PAPER",  INK_FAINT,    PAPER,       0.0),
    ]
    print("[ACBP] design QA (WCAG contrast)")
    for name, fg, bg, need in pairs:
        value = contrast(fg, bg)
        tag = "OK" if value >= need else ("decor only" if need == 0.0 else "LOW")
        print("  %-21s %5.2f:1  %s" % (name, value, tag))
    if cfg is not None:
        w, h = window_size(cfg)
        print("  DPI %.2f  |  canvas %.2f  |  logical %dx%d  |  physical %dx%d"
              % (DPI_SCALE, CANVAS_SCALE, cfg.window_width,
                 cfg.window_height, w, h))
