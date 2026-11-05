# -*- coding: utf-8 -*-
"""
内置皮肤贴图生成器（仅 pygame + 标准库，不引入 Pillow / numpy）
=====================================================================

运行（项目根目录或任意目录均可）：
    python tools/gen_skins.py

产出到 assets/skins/：
    board_wood.png            暖木棋盘（768x768，不透明）
    board_ink.png             夜墨棋盘（768x768，不透明）
    stone_jade_black.png      温玉 · 墨玉黑子（256x256，带 alpha）
    stone_jade_white.png      温玉 · 米白玉白子
    stone_agate_black.png     玛瑙 · 黑曜黑子
    stone_agate_white.png     玛瑙 · 象牙白子

所有随机过程使用固定种子，重复生成结果一致。运行期只读 PNG，
不依赖本脚本；PNG 与脚本一起随仓库提交，便于复现与二次调整。
"""

import math
import os
import random
import sys

import pygame

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "assets", "skins")

BOARD_SIZE = 768
STONE_SIZE = 256


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _packer(surface):
    """返回把 (r,g,b,a) 打包成 PixelArray 整数的函数，并自检字节序。"""
    probe = pygame.Surface((1, 1), pygame.SRCALPHA)
    probe.set_at((0, 0), (12, 34, 56, 78))
    arr = pygame.PixelArray(probe)
    value = int(arr[0, 0])
    del arr
    if value == 0x0C22384E:
        return lambda r, g, b, a: (r << 24) | (g << 16) | (b << 8) | a
    return lambda r, g, b, a: surface.map_rgb((r, g, b, a))


def _clamp8(v):
    return 0 if v < 0 else (255 if v > 255 else int(v))


class Noise:
    """固定种子的值噪声：预生成随机网格 + 双线性采样，可多尺度叠加。"""

    def __init__(self, seed: int, step: int) -> None:
        rng = random.Random(seed)
        self.step = max(2, int(step))
        self.cols = BOARD_SIZE // self.step + 2
        self.rows = BOARD_SIZE // self.step + 2
        self.grid = [[rng.random() for _ in range(self.cols)]
                     for _ in range(self.rows)]

    def at(self, x: float, y: float) -> float:
        fx, fy = x / self.step, y / self.step
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        # 平滑插值，避免网格状硬边
        tx = tx * tx * (3 - 2 * tx)
        ty = ty * ty * (3 - 2 * ty)
        ix = min(ix, self.cols - 2)
        iy = min(iy, self.rows - 2)
        g = self.grid
        top = g[iy][ix] * (1 - tx) + g[iy][ix + 1] * tx
        bottom = g[iy + 1][ix] * (1 - tx) + g[iy + 1][ix + 1] * tx
        return top * (1 - ty) + bottom * ty


def _save(surface: pygame.Surface, filename: str) -> None:
    path = os.path.join(OUT_DIR, filename)
    pygame.image.save(surface, path)
    print("  %-26s %dx%d  %6.1f KB"
          % (filename, surface.get_width(), surface.get_height(),
             os.path.getsize(path) / 1024.0))


# ---------------------------------------------------------------------------
# 棋盘贴图
# ---------------------------------------------------------------------------
def make_board_wood() -> pygame.Surface:
    """胡桃木：纵向年轮 + 细木丝 + 轻微暗角。"""
    size = BOARD_SIZE
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pack = _packer(surf)
    arr = pygame.PixelArray(surf)

    warp = Noise(1201, 96)      # 年轮的大尺度弯曲
    fine = Noise(1202, 8)       # 木丝细纹（纵向）
    blot = Noise(1203, 160)     # 色斑
    rng = random.Random(1204)
    grain = [rng.random() for _ in range(size)]   # 每列的固定细丝偏移

    for y in range(size):
        for x in range(size):
            bend = warp.at(x, y) * 4.6 + 0.7 * math.sin(x * 0.008)
            ring = math.sin((y * 0.130) + bend)
            # 年轮暗带收窄并放淡，避免整块像水波 / 条纹布
            dark = 10.0 if ring > 0.94 else (3.0 if ring > 0.82 else 0.0)
            fiber = (fine.at(x, y) - 0.5) * 20.0
            patch = (blot.at(x, y) - 0.5) * 22.0
            silk = (grain[x] - 0.5) * 12.0
            dx = (x - size / 2) / (size / 2)
            dy = (y - size / 2) / (size / 2)
            vignette = max(0.0, (dx * dx + dy * dy) - 0.35) * 18.0
            d = ring * 5.0 - dark + fiber + patch + silk - vignette
            arr[x, y] = pack(_clamp8(172 + d), _clamp8(130 + d * 0.88),
                             _clamp8(86 + d * 0.72), 255)
    del arr
    return surf


def make_board_ink() -> pygame.Surface:
    """夜墨：深墨石面 + 云雾状低频明暗 + 细颗粒 + 四角压暗。"""
    size = BOARD_SIZE
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pack = _packer(surf)
    arr = pygame.PixelArray(surf)

    cloud = Noise(2201, 128)
    mid = Noise(2202, 40)
    speck = Noise(2203, 6)
    rng = random.Random(2204)

    for y in range(size):
        for x in range(size):
            c = (cloud.at(x, y) - 0.5) * 26.0
            m = (mid.at(x, y) - 0.5) * 12.0
            grain = (speck.at(x, y) - 0.5) * 8.0 + (rng.random() - 0.5) * 3.0
            dx = (x - size / 2) / (size / 2)
            dy = (y - size / 2) / (size / 2)
            vignette = max(0.0, (dx * dx + dy * dy) - 0.20) * 12.0
            d = c + m + grain - vignette
            arr[x, y] = pack(_clamp8(44 + d * 0.85), _clamp8(49 + d * 0.9),
                             _clamp8(56 + d), 255)
    del arr
    return surf


# ---------------------------------------------------------------------------
# 棋子贴图：径向渐变 + 材质纹路 + 左上柔光 + 边缘抗锯齿
# ---------------------------------------------------------------------------
STONE_RECIPES = {
    "stone_jade_black.png":  dict(base=(24, 46, 42), seed=3101,
                                  veins=(48, 92, 82), mode="jade"),
    "stone_jade_white.png":  dict(base=(238, 234, 216), seed=3102,
                                  veins=(178, 196, 178), mode="jade"),
    "stone_agate_black.png": dict(base=(26, 22, 32), seed=3103,
                                  veins=(108, 62, 84), mode="agate"),
    "stone_agate_white.png": dict(base=(247, 239, 220), seed=3104,
                                  veins=(198, 168, 122), mode="agate"),
}


def make_stone(recipe: dict) -> pygame.Surface:
    size = STONE_SIZE
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pack = _packer(surf)
    arr = pygame.PixelArray(surf)

    base = recipe["base"]
    veins = recipe["veins"]
    mode = recipe["mode"]
    n1 = Noise(recipe["seed"], 48)
    n2 = Noise(recipe["seed"] + 1, 14)
    rng = random.Random(recipe["seed"] + 2)

    center = size / 2.0
    radius = size * 0.468
    for y in range(size):
        for x in range(size):
            dx, dy = x - center, y - center
            dist = math.sqrt(dx * dx + dy * dy)
            norm = dist / radius

            # 圆形边缘 2px 抗锯齿
            if norm >= 1.0:
                alpha = _clamp8((1.008 - norm) * radius * 255 / 2.0)
                if alpha <= 0:
                    arr[x, y] = pack(0, 0, 0, 0)
                    continue
            else:
                alpha = 255

            # 球面明暗：中心略亮，边缘压暗；左上方加一处柔光
            shade = 14.0 * (1.0 - norm) - 26.0 * max(0.0, norm - 0.55) ** 1.4
            hx, hy = (dx + radius * 0.34) / radius, (dy + radius * 0.36) / radius
            highlight = 30.0 * math.exp(-(hx * hx + hy * hy) * 5.0)

            if mode == "jade":
                # 玉石：低频絮状云纹，越靠边缘越明显
                t = n1.at(x, y) * 0.72 + n2.at(x, y) * 0.28
                vein = (t - 0.5) * 26.0 * (0.5 + norm * 0.6)
                mix = max(0.0, (t - 0.62) * 2.4)
            else:
                # 玛瑙：斜向条带，随噪声轻微扭曲
                t = n1.at(x, y)
                band = math.sin((x * 0.055 + y * 0.030) + t * 6.0)
                vein = band * 9.0 + (n2.at(x, y) - 0.5) * 9.0
                mix = max(0.0, (band - 0.35) * 0.55)

            grain = (rng.random() - 0.5) * 3.0
            d = shade + highlight + vein + grain
            r = _clamp8(base[0] * (1 - mix) + veins[0] * mix + d)
            g = _clamp8(base[1] * (1 - mix) + veins[1] * mix + d)
            b = _clamp8(base[2] * (1 - mix) + veins[2] * mix + d)
            arr[x, y] = pack(r, g, b, alpha)
    del arr
    return surf


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("[ACBP] 生成内置皮肤贴图 → %s" % OUT_DIR)
    _save(make_board_wood(), "board_wood.png")
    _save(make_board_ink(), "board_ink.png")
    for filename, recipe in STONE_RECIPES.items():
        _save(make_stone(recipe), filename)
    print("[ACBP] 完成，共 6 张贴图。")


if __name__ == "__main__":
    # 无需 pygame.init() / display：Surface 与 image.save 在纯 SDL 下即可工作
    main()
