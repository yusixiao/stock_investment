from tests.utils_test_helpers import MockContext
from strategies.utils import kline


def _bar(date, open_, close, low=None, high=None, volume=1000):
    return {
        "date": date,
        "open": open_,
        "close": close,
        "low": low if low is not None else min(open_, close),
        "high": high if high is not None else max(open_, close),
        "volume": volume,
    }


# ===== is_at_history_low =====


def test_is_at_history_low_within_range_passes():
    """current_low=10.5,过去 36 月最低=10.0,range_pct=20% → 阈值=12.0,通过。"""
    bars = [_bar(f"2021-{m:02d}", 20, 21, low=20) for m in range(1, 13)]
    bars += [_bar(f"2022-{m:02d}", 15, 16, low=10) for m in range(1, 13)]
    bars += [_bar(f"2023-{m:02d}", 12, 13, low=12) for m in range(1, 13)]
    bars += [_bar("2024-01", 11, 12, low=10.5)]

    ctx = MockContext(history={"A__monthly": bars})
    assert (
        kline.is_at_history_low(ctx, "A", years=3, range_pct=20.0, freq="monthly")
        is True
    )
    assert ctx.pass_logs and ctx.pass_logs[0][1] == "kline.history_low"


def test_is_at_history_low_above_range_fails():
    bars = [_bar(f"2021-{m:02d}", 20, 21, low=20) for m in range(1, 13)]
    bars += [_bar(f"2022-{m:02d}", 15, 16, low=10) for m in range(1, 13)]
    bars += [_bar(f"2023-{m:02d}", 12, 13, low=12) for m in range(1, 13)]
    bars += [_bar("2024-01", 16, 17, low=15)]

    ctx = MockContext(history={"A__monthly": bars})
    assert (
        kline.is_at_history_low(ctx, "A", years=3, range_pct=20.0, freq="monthly")
        is False
    )
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "above_threshold"


def test_is_at_history_low_insufficient_history():
    bars = [_bar(f"2024-{m:02d}", 10, 11, low=10) for m in range(1, 6)]
    ctx = MockContext(history={"A__monthly": bars})
    assert (
        kline.is_at_history_low(ctx, "A", years=3, range_pct=20.0, freq="monthly")
        is False
    )
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "no_data"


# ===== has_consecutive_red_bars =====


def test_has_consecutive_red_bars_all_red():
    bars = [_bar(f"2024-{m:02d}", 10, 11) for m in range(1, 5)]
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is True
    assert ctx.pass_logs and ctx.pass_logs[0][1] == "kline.consecutive_red"


def test_has_consecutive_red_bars_one_green_breaks():
    bars = [
        _bar("2024-01", 10, 11),
        _bar("2024-02", 11, 10),
        _bar("2024-03", 10, 12),
        _bar("2024-04", 12, 13),
    ]
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "not_all_red"


def test_has_consecutive_red_bars_close_equal_open_counts_as_red():
    bars = [_bar("2024-01", 10, 10) for _ in range(4)]
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is True


def test_has_consecutive_red_bars_insufficient_data():
    bars = [_bar("2024-01", 10, 11), _bar("2024-02", 11, 12)]
    ctx = MockContext(history={"A__monthly": bars})
    assert kline.has_consecutive_red_bars(ctx, "A", n=4, freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "no_data"
