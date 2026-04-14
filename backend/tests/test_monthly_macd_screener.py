import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

from monthly_macd_positive_screener import MonthlyMacdPositiveScreener


def _make_monthly_records(monthly_closes):
    records = []
    for i, close in enumerate(monthly_closes):
        year = 2020 + i // 12
        month = i % 12 + 1
        records.append({
            "date": f"{year:04d}-{month:02d}-28",
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 1000000.0,
            "amount": close * 1000000.0,
        })
    return records


class TestMonthlyMacdPositiveScreener:
    def _make_ctx(self, history_data):
        ctx = MagicMock()
        ctx.get_history = MagicMock(side_effect=lambda sym, n: history_data.get(sym, [])[-n:])
        return ctx

    def test_steady_uptrend_selected(self):
        closes = [10 + i * 0.5 for i in range(40)]
        records = _make_monthly_records(closes)
        ctx = self._make_ctx({"000001": records})
        s = MonthlyMacdPositiveScreener()
        result = s.screen(ctx, ["000001"])
        assert "000001" in result

    def test_downtrend_not_selected(self):
        closes = [50 - i * 0.5 for i in range(40)]
        records = _make_monthly_records(closes)
        ctx = self._make_ctx({"000001": records})
        s = MonthlyMacdPositiveScreener()
        result = s.screen(ctx, ["000001"])
        assert "000001" not in result

    def test_too_short_history(self):
        records = _make_monthly_records([10.0] * 10)
        ctx = self._make_ctx({"000001": records})
        s = MonthlyMacdPositiveScreener()
        result = s.screen(ctx, ["000001"])
        assert result == []

    def test_custom_consecutive_months(self):
        s = MonthlyMacdPositiveScreener(param_overrides={"consecutive_months": 6})
        assert s.p.consecutive_months == 6

    def test_frequency_is_monthly(self):
        s = MonthlyMacdPositiveScreener()
        assert s.frequency == "monthly"

    def test_mixed_macd_not_selected(self):
        closes = [10.0] * 30
        closes.extend([10.0, 9.5, 10.5, 9.8])
        records = _make_monthly_records(closes)
        ctx = self._make_ctx({"000001": records})
        s = MonthlyMacdPositiveScreener()
        result = s.screen(ctx, ["000001"])
        assert "000001" not in result
