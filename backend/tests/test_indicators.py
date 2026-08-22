"""indicators.py 单元测试 — 验证预算指标列与查表入口语义。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.backtest.indicators import (
    DEFAULT_MACD_PARAMS,
    STANDARD_MA_WINDOWS,
    compute_indicators,
    resolve_indicator_column,
)


def _make_df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    dates = [f"2024-01-{i + 1:02d}" for i in range(n)]
    df = pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
        }
    )
    if volumes is not None:
        df["volume"] = volumes
    return df


def test_ma_windows_present_and_correct():
    closes = list(range(1, 41))  # 40 根 bar,1..40
    df = compute_indicators(_make_df(closes))
    for w in STANDARD_MA_WINDOWS:
        assert f"ma{w}" in df.columns
        # 第 w-1 行起才有值,前面是 NaN
        assert np.isnan(df[f"ma{w}"].iloc[w - 2])
        # 最后一行 = 最后 w 个 close 的平均
        expected = sum(closes[-w:]) / w
        assert df[f"ma{w}"].iloc[-1] == pytest.approx(expected)


def test_ema_and_macd_columns_match_legacy_ema():
    """新 EMA 末尾值应与 strategies/utils/kline._ema 末尾一致(项目硬性约定)。"""
    from services.backtest.strategies.utils.kline import _ema as legacy_ema

    closes = [10.0 + 0.1 * i for i in range(60)]
    df = compute_indicators(_make_df(closes))
    legacy_e12 = legacy_ema(closes, 12)
    legacy_e26 = legacy_ema(closes, 26)
    assert df["ema12"].iloc[-1] == pytest.approx(legacy_e12[-1])
    assert df["ema26"].iloc[-1] == pytest.approx(legacy_e26[-1])

    # macd_hist = 2 × (DIF - DEA),AGENTS.md 硬性约定
    dif_last = df["macd_dif"].iloc[-1]
    dea_last = df["macd_dea"].iloc[-1]
    hist_last = df["macd_hist"].iloc[-1]
    assert hist_last == pytest.approx(2.0 * (dif_last - dea_last))


def test_volume_ma_only_when_volume_present():
    closes = [1.0] * 20
    df_no_vol = compute_indicators(_make_df(closes))
    assert "vol_ma5" not in df_no_vol.columns

    df_with_vol = compute_indicators(_make_df(closes, volumes=[100.0] * 20))
    assert df_with_vol["vol_ma5"].iloc[-1] == pytest.approx(100.0)


def test_compute_indicators_accepts_missing_close_values():
    frame = _make_df([1.0, 2.0, 3.0])
    frame["close"] = pd.Series([pd.NA, 2.0, 3.0], dtype="object")

    result = compute_indicators(frame)

    assert "ma5" in result.columns
    assert result["ema12"].dtype == np.dtype(float)


def test_ret_1_and_vol_20d():
    closes = [10.0, 11.0, 12.1]
    df = compute_indicators(_make_df(closes))
    assert np.isnan(df["ret_1"].iloc[0])
    assert df["ret_1"].iloc[1] == pytest.approx(0.1)
    assert df["ret_1"].iloc[2] == pytest.approx((12.1 - 11.0) / 11.0)
    # 数据不足 20 行,vol_20d 全 NaN
    assert df["vol_20d"].isna().all()


def test_compute_indicators_idempotent_on_empty():
    empty = pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    out = compute_indicators(empty)
    assert out.empty


def test_resolve_indicator_column_standard_windows():
    assert resolve_indicator_column("ma", window=20) == "ma20"
    assert resolve_indicator_column("ma20") == "ma20"
    assert resolve_indicator_column("ma", window=15) is None  # 非标准窗口
    assert resolve_indicator_column("ma15") is None
    assert resolve_indicator_column("ema", window=12) == "ema12"
    assert resolve_indicator_column("ema50") is None
    assert resolve_indicator_column("vol_ma", window=5) == "vol_ma5"


def test_resolve_indicator_column_macd():
    assert resolve_indicator_column("macd", field="dif") == "macd_dif"
    assert resolve_indicator_column("macd", field="hist") == "macd_hist"
    assert resolve_indicator_column("macd_dea") == "macd_dea"
    # 非默认参数 → 不命中
    fast, slow, signal = DEFAULT_MACD_PARAMS
    assert (
        resolve_indicator_column(
            "macd", field="dif", fast=fast, slow=slow, signal=signal
        )
        == "macd_dif"
    )
    assert resolve_indicator_column("macd", field="dif", fast=10) is None
    # 未知 field
    assert resolve_indicator_column("macd", field="bogus") is None


def test_resolve_indicator_column_misc():
    assert resolve_indicator_column("ret_1") == "ret_1"
    assert resolve_indicator_column("vol_20d") == "vol_20d"
    assert resolve_indicator_column("unknown") is None
