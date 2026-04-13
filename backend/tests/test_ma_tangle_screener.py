import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from unittest.mock import MagicMock

from ma_tangle_breakout_screener import MaTangleBreakoutScreener, _monthly_ma


def _make_daily_records(monthly_closes):
    records = []
    for i, close in enumerate(monthly_closes):
        year = 2020 + i // 12
        month = i % 12 + 1
        for day in [5, 15, 25]:
            records.append({
                "date": f"{year:04d}-{month:02d}-{day:02d}",
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1000000.0,
                "amount": close * 1000000.0,
            })
    return records


class TestMonthlyMa:
    def test_basic(self):
        closes = [10 + i * 0.1 for i in range(24)]
        records = _make_daily_records(closes)
        result = _monthly_ma(records, [5, 10, 20])
        assert "ma5" in result.columns
        assert "ma10" in result.columns
        assert "ma20" in result.columns
        assert len(result) == 24
        assert pd.notna(result.iloc[-1]["ma5"])
        assert pd.notna(result.iloc[-1]["ma20"])

    def test_too_short(self):
        result = _monthly_ma([{"date": "2020-01-01", "close": 10}], [5])
        assert result.empty


class TestMaTangleBreakoutScreener:
    def _make_ctx(self, history_data):
        ctx = MagicMock()
        ctx.get_history = MagicMock(side_effect=lambda sym, n: history_data.get(sym, []))
        return ctx

    def test_tangle_then_breakthrough_selected(self):
        monthly_closes = [10.0] * 20
        monthly_closes.extend([10.0, 10.0, 10.0])
        monthly_closes.append(10.5)
        records = _make_daily_records(monthly_closes)
        monthly = _monthly_ma(records, [5, 10, 20])
        last = monthly.iloc[-1]
        assert last["ma5"] > last["ma20"]

        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" in result

    def test_no_tangle_not_selected(self):
        monthly_closes = list(range(1, 25))
        records = _make_daily_records(monthly_closes)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" not in result

    def test_too_short_history(self):
        records = _make_daily_records([10.0] * 5)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert result == []

    def test_custom_params(self):
        s = MaTangleBreakoutScreener(param_overrides={"threshold": 0.10, "tangle_months": 3})
        assert s.p.threshold == 0.10
        assert s.p.tangle_months == 3

    def test_no_breakthrough_not_selected(self):
        monthly_closes = [10.0] * 24
        records = _make_daily_records(monthly_closes)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" not in result

    def test_breakthrough_without_enough_tangle(self):
        monthly_closes = list(range(10, 33))
        monthly_closes[-3] = monthly_closes[-2] = monthly_closes[-1] + 0.01
        records = _make_daily_records(monthly_closes)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" not in result
