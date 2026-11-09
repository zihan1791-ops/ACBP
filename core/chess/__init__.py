# -*- coding: utf-8 -*-
"""中国象棋规则包。"""
from .board import ChessBoard, decode_sq, encode_sq, piece_name, piece_side

__all__ = ["ChessBoard", "encode_sq", "decode_sq", "piece_name", "piece_side"]
