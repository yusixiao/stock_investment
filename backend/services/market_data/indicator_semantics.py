"""跨市场数据展示与回测共用的指标语义。"""

from __future__ import annotations

import numpy as np


MACD_HIST_MULTIPLIER = 2.0
STANDARD_MA_WINDOWS: tuple[int, ...] = (5, 10, 20, 30)
STANDARD_EMA_WINDOWS: tuple[int, ...] = (12, 26)
DEFAULT_MACD_PARAMS: tuple[int, int, int] = (12, 26, 9)


def ema(values: np.ndarray, window: int) -> np.ndarray:
    """使用窗口首个 SMA 初始化 EMA，保证展示和回测采用同一暖机语义。"""
    numeric = np.asarray(values, dtype=float)
    result = np.full(len(numeric), np.nan, dtype=float)
    if len(numeric) < window:
        return result
    result[window - 1] = float(numeric[:window].mean())
    alpha = 2.0 / (window + 1)
    for index in range(window, len(numeric)):
        result[index] = result[index - 1] + alpha * (
            numeric[index] - result[index - 1]
        )
    return result


def macd(
    values: np.ndarray,
    fast: int = DEFAULT_MACD_PARAMS[0],
    slow: int = DEFAULT_MACD_PARAMS[1],
    signal: int = DEFAULT_MACD_PARAMS[2],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回 DIF、DEA、MACD bar，bar 固定为 2 × (DIF - DEA)。"""
    numeric = np.asarray(values, dtype=float)
    dif = ema(numeric, fast) - ema(numeric, slow)
    dea = np.full(len(numeric), np.nan, dtype=float)
    valid = ~np.isnan(dif)
    if valid.any():
        first_valid = int(np.argmax(valid))
        dea[first_valid:] = ema(dif[first_valid:], signal)
    return dif, dea, MACD_HIST_MULTIPLIER * (dif - dea)
