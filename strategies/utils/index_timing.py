"""指数择时工具(沪深300 MA200 等),用于策略层的「大盘趋势过滤」。

数据来源:`data/market/A/index/sh000300.parquet`(由 scripts 离线 baostock 拉取,
日期降序,字段 date/open/high/low/close/volume/amount)。

用法:
    from strategies.utils.index_timing import csi300_is_bull
    if not csi300_is_bull(date_str, ma_period=200):
        return []  # 空仓
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_INDEX_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "market"
    / "A"
    / "index"
    / "sh000300.parquet"
)


@lru_cache(maxsize=1)
def _load_csi300() -> pd.DataFrame:
    """一次加载 CSI300 历史,升序排列。"""
    df = pd.read_parquet(_INDEX_PATH)
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = df["date"].astype(str)
    return df


def csi300_is_bull(date_str: str, ma_period: int = 200) -> bool:
    """date_str 当日(或最近一个交易日)CSI300 close > MA(ma_period)。

    若数据不足或日期超出范围,**保守返回 True**(不阻止建仓,行为同基线)。
    """
    if not date_str:
        return True
    df = _load_csi300()
    target = str(date_str)[:10]
    # 找 <= target 的最后一行
    idx = df["date"].searchsorted(target, side="right") - 1
    if idx < 0:
        return True  # 数据起点之前,无法判断 → 不拦截
    if idx < ma_period:
        return True  # MA 未充满 → 不拦截
    window = df["close"].iloc[idx - ma_period + 1 : idx + 1].to_numpy(dtype=float)
    ma = float(np.mean(window))
    last_close = float(df["close"].iloc[idx])
    return last_close > ma
