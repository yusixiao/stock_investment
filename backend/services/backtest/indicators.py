"""指标预计算模块(2026-05-22 引入)。

设计动机:
- 旧路径每根 bar 调 ctx.get_history(N) 再 Python 求和算 MA / EMA / MACD,
  N_bars × N_symbols × O(window) 在月线 + 月线 MA20 + 6000 标的下可达数千万次。
- 新路径数据加载时一次性算好所有标准指标,落到 DataFrame 列上,运行时 O(1) 查表。
- 标准窗口集(用户确认 2026-05-22):MA 5/10/20/30 + EMA12/26 + MACD(默认 12/26/9)
  + VOL_MA5/10 + RET_1 + VOL_20D。非标准参数走 fallback 路径(strategies/utils/kline.py)。

输出列(在原 daily/weekly/monthly DF 上 in-place 增加):
- ma5, ma10, ma20, ma30
- ema12, ema26
- macd_dif, macd_dea, macd_hist  (hist = 2 × (DIF - DEA),项目硬性约定)
- vol_ma5, vol_ma10
- ret_1   (close 的环比收益,(close_t - close_{t-1}) / close_{t-1})
- vol_20d (ret_1 的 20 期滚动标准差)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.market_data.indicator_semantics import (
    DEFAULT_MACD_PARAMS,
    MACD_HIST_MULTIPLIER,
    STANDARD_EMA_WINDOWS,
    STANDARD_MA_WINDOWS,
    ema,
    macd,
)

STANDARD_VOL_MA_WINDOWS: tuple[int, ...] = (5, 10)
DEFAULT_VOLATILITY_WINDOW: int = 20


def _ema(values: np.ndarray, window: int) -> np.ndarray:
    """兼容旧内部调用，实际语义集中在 indicator_semantics。"""
    return ema(values, window)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """对单只股票升序 DataFrame 追加标准指标列。

    入参约束:
    - df 至少含 ``date / open / high / low / close``,可含 ``volume`` / ``amount``
    - date 升序排列(_load_market_blocking 用 query_qfq_kline_bulk 已保证)
    - 不修改入参,返回新 DataFrame(共享底层 buffer 安全:仅追加列)

    数据不足时(行数 < 窗口)对应位置填 NaN,策略读到 NaN 应当作"无效"处理。
    """
    if df is None or df.empty or "close" not in df.columns:
        return df

    # 不破坏原始 df:浅拷贝列指针即可
    out = df.copy(deep=False)
    closes = out["close"].to_numpy(dtype=float, na_value=np.nan)

    # ---- MA(简单移动平均,close)----
    close_series = pd.Series(closes)
    for w in STANDARD_MA_WINDOWS:
        out[f"ma{w}"] = close_series.rolling(window=w, min_periods=w).mean().to_numpy()

    # ---- EMA(close)----
    for w in STANDARD_EMA_WINDOWS:
        out[f"ema{w}"] = _ema(closes, w)

    # ---- MACD(默认 12/26/9,DIF=EMA_fast - EMA_slow,DEA=EMA(DIF, signal),
    #          HIST = 2 × (DIF - DEA))----
    fast, slow, signal = DEFAULT_MACD_PARAMS
    dif, dea, hist = macd(closes, fast, slow, signal)
    out["macd_dif"] = dif
    out["macd_dea"] = dea
    out["macd_hist"] = hist

    # ---- VOL_MA(成交量简单移动平均)----
    if "volume" in out.columns:
        vol_series = out["volume"].astype(float)
        for w in STANDARD_VOL_MA_WINDOWS:
            out[f"vol_ma{w}"] = (
                vol_series.rolling(window=w, min_periods=w).mean().to_numpy()
            )

    # ---- 收益率与短期波动率 ----
    ret_1 = close_series.pct_change().to_numpy()
    out["ret_1"] = ret_1
    out["vol_20d"] = (
        pd.Series(ret_1)
        .rolling(
            window=DEFAULT_VOLATILITY_WINDOW, min_periods=DEFAULT_VOLATILITY_WINDOW
        )
        .std()
        .to_numpy()
    )

    return out


# ---- 查表入口(供 MarketData.get_indicator 用)----


# 名字映射:外部接口允许 "ma" + window kwarg 或固定列名 "ma5"。统一规范化到列名。
def resolve_indicator_column(name: str, **kwargs) -> str | None:
    """把 (name, kwargs) 解析为 compute_indicators 输出的列名;不匹配返回 None。

    支持:
    - ma / window=N        → ma{N}  (N ∈ STANDARD_MA_WINDOWS)
    - ema / window=N       → ema{N} (N ∈ STANDARD_EMA_WINDOWS)
    - vol_ma / window=N    → vol_ma{N}
    - macd / field="dif"|"dea"|"hist" / fast=12 slow=26 signal=9
                           → macd_{field}  (仅默认参数命中)
    - ret_1                → ret_1
    - vol_20d              → vol_20d
    - 直接传完整列名(如 "ma20" / "macd_dif")透传
    """
    name_l = name.lower()

    # 直接列名透传(策略代码方便)
    if name_l in {"ret_1", "vol_20d"}:
        return name_l
    if name_l.startswith("ma") and name_l[2:].isdigit():
        return name_l if int(name_l[2:]) in STANDARD_MA_WINDOWS else None
    if name_l.startswith("ema") and name_l[3:].isdigit():
        return name_l if int(name_l[3:]) in STANDARD_EMA_WINDOWS else None
    if name_l.startswith("vol_ma") and name_l[6:].isdigit():
        return name_l if int(name_l[6:]) in STANDARD_VOL_MA_WINDOWS else None
    if name_l in {"macd_dif", "macd_dea", "macd_hist"}:
        return name_l

    # 带 kwargs 的语义化入口
    if name_l == "ma":
        w = kwargs.get("window")
        if isinstance(w, int) and w in STANDARD_MA_WINDOWS:
            return f"ma{w}"
        return None
    if name_l == "ema":
        w = kwargs.get("window")
        if isinstance(w, int) and w in STANDARD_EMA_WINDOWS:
            return f"ema{w}"
        return None
    if name_l == "vol_ma":
        w = kwargs.get("window")
        if isinstance(w, int) and w in STANDARD_VOL_MA_WINDOWS:
            return f"vol_ma{w}"
        return None
    if name_l == "macd":
        # 仅默认 12/26/9 命中预算列;非默认参数让上层走 fallback
        fast = kwargs.get("fast", DEFAULT_MACD_PARAMS[0])
        slow = kwargs.get("slow", DEFAULT_MACD_PARAMS[1])
        signal = kwargs.get("signal", DEFAULT_MACD_PARAMS[2])
        if (fast, slow, signal) != DEFAULT_MACD_PARAMS:
            return None
        field = str(kwargs.get("field", "dif")).lower()
        if field in {"dif", "dea", "hist"}:
            return f"macd_{field}"
        return None

    return None
