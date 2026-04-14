import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from unittest.mock import MagicMock

from ma_tangle_breakout_screener import MaTangleBreakoutScreener


def _make_monthly_records(monthly_closes):
    records = []
    for i, close in enumerate(monthly_closes):
        year = 2020 + i // 12
        month = i % 12 + 1
        records.append({
            "date": f"{year:04d}-{month:02d}-28",
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000000.0,
            "amount": close * 1000000.0,
        })
    return records


class TestMaTangleBreakoutScreener:
    def _make_ctx(self, history_data):
        ctx = MagicMock()
        ctx.get_history = MagicMock(side_effect=lambda sym, n: history_data.get(sym, [])[-n:])
        return ctx

    def test_tangle_selected(self):
        monthly_closes = [10.0] * 24
        records = _make_monthly_records(monthly_closes)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" in result

    def test_no_tangle_not_selected(self):
        monthly_closes = list(range(1, 25))
        records = _make_monthly_records(monthly_closes)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" not in result

    def test_too_short_history(self):
        records = _make_monthly_records([10.0] * 5)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert result == []

    def test_custom_params(self):
        s = MaTangleBreakoutScreener(param_overrides={"threshold": 0.10, "tangle_months": 3})
        assert s.p.threshold == 0.10
        assert s.p.tangle_months == 3

    def test_not_enough_tangle_months(self):
        monthly_closes = list(range(10, 33))
        monthly_closes[-1] = monthly_closes[-2]
        records = _make_monthly_records(monthly_closes)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert "000001.SZ" not in result

    def test_frequency_is_monthly(self):
        s = MaTangleBreakoutScreener()
        assert s.frequency == "monthly"
