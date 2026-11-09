# -*- coding: utf-8 -*-
"""算法加速层：批量局面评估（CPU numpy / 可选 GPU CUDA）。"""
from .batch import backend_name, batch_scores, gpu_available

__all__ = ["batch_scores", "gpu_available", "backend_name"]
