import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from unittest.mock import MagicMock

from ma_tangle_breakout_screener import MaTangleBreakoutScreener


def _make_records(prices):
    records = []
    for i, (o, c) in enumerate(prices):
        year = 2020 + i // 12
        month = i % 12 + 1
        records.append({
            "date": f"{year:04d}-{month:02d}-28",
            "open": o,
            "high": max(o, c) * 1.01,
            "low": min(o, c) * 0.99,
            "close": c,
            "volume": 1000000.0,
            "amount": c * 1000000.0,
        })
    return records


class TestMaTangleBreakoutScreener:
    def _make_ctx(self, history_data):
        ctx = MagicMock()
        ctx.get_history = MagicMock(side_effect=lambda sym, n: history_data.get(sym, [])[-n:])
        return ctx

    def _build_tangle_then_spread(self):
        flat = [(10.0, 10.0)] * 22
        spread = [
            (10.0, 11.0),
            (11.0, 12.0),
            (12.0, 13.0),
            (13.0, 14.0),
            (14.0, 15.0),
            (15.0, 16.0),
        ]
        return flat + spread

    def test_tangle_then_spread_selected(self):
        prices = self._build_tangle_then_spread()
        records = _make_records(prices)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        syms = [item["symbol"] if isinstance(item, dict) else item for item in result]
        assert "000001.SZ" in syms

    def test_match_date_is_first_red_bar(self):
        prices = self._build_tangle_then_spread()
        records = _make_records(prices)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["symbol"] == "000001.SZ"
        assert result[0]["match_date"] == records[23]["date"]

    def test_no_tangle_not_selected(self):
        prices = [(float(i), float(i)) for i in range(1, 29)]
        records = _make_records(prices)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert result == []

    def test_too_short_history(self):
        records = _make_records([(10.0, 10.0)] * 5)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert result == []

    def test_custom_params(self):
        s = MaTangleBreakoutScreener(param_overrides={"threshold": 0.10, "tangle_months": 3})
        assert s.p.threshold == 0.10
        assert s.p.tangle_months == 3

    def test_tangle_without_spread_not_selected(self):
        prices = [(10.0, 10.0)] * 28
        records = _make_records(prices)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert result == []

    def test_spread_without_enough_red_bars(self):
        flat = [(10.0, 10.0)] * 22
        spread = [
            (10.0, 11.0),
            (12.0, 11.5),
            (11.5, 12.5),
            (13.0, 12.0),
            (12.0, 13.0),
            (13.0, 14.0),
        ]
        prices = flat + spread
        records = _make_records(prices)
        ctx = self._make_ctx({"000001.SZ": records})
        s = MaTangleBreakoutScreener()
        result = s.screen(ctx, ["000001.SZ"])
        assert result == []

    def test_frequency_is_monthly(self):
        s = MaTangleBreakoutScreener()
        assert s.frequency == "monthly"
