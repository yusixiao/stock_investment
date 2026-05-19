import math

from tests.utils_test_helpers import MockContext
from strategies.utils import kline


def _bars(closes, opens=None, highs=None, lows=None, vols=None):
    n = len(closes)
    return [
        {
            "date": f"2024-{i + 1:02d}-01",
            "open": (opens[i] if opens else closes[i]),
            "close": closes[i],
            "high": (
                highs[i]
                if highs
                else max(closes[i], (opens[i] if opens else closes[i]))
            ),
            "low": (
                lows[i] if lows else min(closes[i], (opens[i] if opens else closes[i]))
            ),
            "volume": (vols[i] if vols else 1000),
        }
        for i in range(n)
    ]


def test_get_ma_basic():
    ctx = MockContext(history={"A": _bars([10, 11, 12, 13, 14])})
    assert kline.get_ma(ctx, "A", window=5) == 12.0


def test_get_ma_insufficient_data_returns_none():
    ctx = MockContext(history={"A": _bars([10, 11])})
    assert kline.get_ma(ctx, "A", window=5) is None


def test_get_ma_no_history_returns_none():
    ctx = MockContext()
    assert kline.get_ma(ctx, "A", window=5) is None


def test_get_ma_uses_last_n_only():
    """如果有 10 根 bar,MA5 应只用最后 5 根。"""
    ctx = MockContext(history={"A": _bars([1, 2, 3, 4, 5, 10, 11, 12, 13, 14])})
    assert kline.get_ma(ctx, "A", window=5) == 12.0


def test_get_macd_dif_basic():
    """足够数据时 dif 应为有限数(具体值用宽松断言)。"""
    closes = [10 + 0.1 * i for i in range(40)]
    ctx = MockContext(history={"A": _bars(closes)})
    dif = kline.get_macd(ctx, "A", field="dif")
    assert dif is not None and not math.isnan(dif)


def test_get_macd_hist_equals_2x_dif_minus_dea():
    closes = [10 + 0.1 * i for i in range(40)]
    ctx = MockContext(history={"A": _bars(closes)})
    dif = kline.get_macd(ctx, "A", field="dif")
    dea = kline.get_macd(ctx, "A", field="dea")
    hist = kline.get_macd(ctx, "A", field="hist")
    assert abs(hist - 2 * (dif - dea)) < 1e-9


def test_get_macd_insufficient_data_returns_none():
    """少于 26 根 bar(慢线周期)→ None。"""
    closes = [10, 11, 12]
    ctx = MockContext(history={"A": _bars(closes)})
    assert kline.get_macd(ctx, "A", field="dif") is None


def test_get_macd_invalid_field_raises():
    closes = [10 + 0.1 * i for i in range(40)]
    ctx = MockContext(history={"A": _bars(closes)})
    import pytest

    with pytest.raises(ValueError, match="field"):
        kline.get_macd(ctx, "A", field="bogus")


def test_get_ma_freq_param_routes_to_period_history():
    """freq=monthly 应通过 ctx.get_history 拿到 monthly 数据。"""
    daily_bars = _bars([1, 2, 3, 4, 5])
    monthly_bars = _bars([100, 110, 120, 130, 140])
    ctx = MockContext(history={"A": daily_bars, "A__monthly": monthly_bars})
    assert kline.get_ma(ctx, "A", window=5, freq="monthly") == 120.0
    assert kline.get_ma(ctx, "A", window=5, freq="daily") == 3.0
