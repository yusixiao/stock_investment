"""detect_ma_tangle_breakout 单测。

数值精度对齐 vs 旧 MaTangleBreakoutScreener 在 Phase 6 回归测覆盖,本 task 仅验证结构性正确。
"""

from tests.utils_test_helpers import MockContext
from strategies.utils import kline


def _bars_from_closes(closes, opens=None, vols=None):
    n = len(closes)
    return [
        {
            "date": f"2024-{i + 1:02d}-01" if i < 12 else f"2025-{(i - 11):02d}-01",
            "open": (opens[i] if opens else closes[i]),
            "close": closes[i],
            "high": max(closes[i], (opens[i] if opens else closes[i])),
            "low": min(closes[i], (opens[i] if opens else closes[i])),
            "volume": (vols[i] if vols else 1000),
        }
        for i in range(n)
    ]


def test_detect_ma_tangle_breakout_no_data_returns_false():
    ctx = MockContext()
    assert kline.detect_ma_tangle_breakout(ctx, "X", freq="monthly") is False
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "no_data"


def test_detect_ma_tangle_breakout_insufficient_history():
    bars = _bars_from_closes([10] * 10)  # < slow + tangle_months + spread_months
    ctx = MockContext(history={"A__monthly": bars})
    assert (
        kline.detect_ma_tangle_breakout(
            ctx, "A", slow=20, tangle_months=2, freq="monthly"
        )
        is False
    )
    assert ctx.reject_logs and ctx.reject_logs[0][2] == "insufficient_history"


def test_detect_ma_tangle_breakout_flat_then_uptrend_signal():
    """构造:前 25 月横盘价格 ≈ 10(MA 缠绕)→ 后 6 月持续上涨(MA 发散+连续阳线)。
    应该返回 True。"""
    # 渐进式上涨:前几根缓涨(spread 不达标 → 早期 tangle_end 不会"burn"
    # skip_until),后几根加速,使 tangle_end=7 成为首个完全成立的候选,
    # 其 spread_window 恰好覆盖 last_idx。
    flat = [10.0] * 25
    up = [10.2, 10.5, 11.0, 12.5, 16.0, 22.0]
    closes = flat + up
    opens = flat + [9.8, 10.2, 10.5, 11.0, 12.5, 16.0]
    bars = _bars_from_closes(closes, opens=opens)
    ctx = MockContext(history={"A__monthly": bars})

    assert (
        kline.detect_ma_tangle_breakout(
            ctx,
            "A",
            fast=5,
            mid=10,
            slow=20,
            tangle_threshold=0.05,
            tangle_months=2,
            spread_months=4,
            spread_threshold=0.01,
            macd_red_bars=4,
            freq="monthly",
        )
        is True
    )
    assert any(p[1] == "kline.ma_tangle" for p in ctx.pass_logs)


def test_detect_ma_tangle_breakout_no_tangle_returns_false():
    """单调上涨,从未缠绕,应返回 False。"""
    closes = [10 + i * 0.5 for i in range(40)]
    bars = _bars_from_closes(closes)
    ctx = MockContext(history={"A__monthly": bars})
    assert (
        kline.detect_ma_tangle_breakout(
            ctx, "A", slow=20, tangle_months=2, freq="monthly"
        )
        is False
    )


def test_detect_ma_tangle_breakout_tangle_no_spread():
    """全程横盘,从未发散,应返回 False。"""
    closes = [10.0 + 0.01 * (i % 3) for i in range(40)]
    bars = _bars_from_closes(closes)
    ctx = MockContext(history={"A__monthly": bars})
    assert (
        kline.detect_ma_tangle_breakout(
            ctx, "A", slow=20, tangle_months=2, spread_months=4, freq="monthly"
        )
        is False
    )
