import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))

import pytest
import pandas as pd
from config import QFQ_KLINE_DIR
from services.stock_data import aggregate_kline
from unittest.mock import MagicMock

DATA_AVAILABLE = QFQ_KLINE_DIR.exists() and any(QFQ_KLINE_DIR.glob("*.parquet"))

skip_no_data = pytest.mark.skipif(not DATA_AVAILABLE, reason="qfq parquet data not available")


def _load_monthly(symbol: str) -> list[dict]:
    df = pd.read_parquet(QFQ_KLINE_DIR / f"{symbol}.parquet")
    df = df.sort_values("date").reset_index(drop=True)
    monthly = aggregate_kline(df, period="monthly")
    monthly = monthly.sort_values("date").reset_index(drop=True)
    return monthly.to_dict(orient="records")


def _make_ctx(history_data: dict[str, list[dict]]):
    ctx = MagicMock()
    ctx.get_history = MagicMock(
        side_effect=lambda sym, n: (
            history_data.get(sym, [])[-n:] if n < len(history_data.get(sym, [])) else history_data.get(sym, [])
        )
    )
    return ctx


def _screen_single(symbol: str):
    from ma_tangle_breakout_screener import MaTangleBreakoutScreener
    records = _load_monthly(symbol)
    ctx = _make_ctx({symbol: records})
    s = MaTangleBreakoutScreener()
    result = s.screen(ctx, [symbol])
    dates = []
    for item in result:
        if isinstance(item, dict):
            dates.append(item["match_date"])
        else:
            dates.append(None)
    return dates


def _engine_backtest(symbols: list[str]) -> dict[str, list[str]]:
    from services.backtest.engine import BacktestEngine
    from ma_tangle_breakout_screener import MaTangleBreakoutScreener
    stock_data = {}
    for sym in symbols:
        df = pd.read_parquet(QFQ_KLINE_DIR / f"{sym}.parquet")
        df = df.sort_values("date").reset_index(drop=True)
        stock_data[sym] = df
    screener = MaTangleBreakoutScreener()
    engine = BacktestEngine(stock_data=stock_data, screeners=[screener])
    result = engine.run(mode="auto")
    out = {}
    for item in result["screened_symbols"]:
        out[item["symbol"]] = item["match_dates"]
    return out


EXPECTED_LATEST_MATCH = {
    "000629.SZ": "2025-11-28",
    "301083.SZ": "2025-07-31",
    "002056.SZ": "2025-06-30",
    "002870.SZ": "2025-06-30",
    "300041.SZ": "2025-06-30",
    "300221.SZ": "2025-01-27",
}

EXPECTED_ALL_MATCH_DATES = {
    "000629.SZ": ["2010-11", "2025-11"],
    "301083.SZ": ["2025-07"],
    "002056.SZ": ["2025-06"],
    "002870.SZ": ["2025-06"],
    "300041.SZ": ["2025-06"],
    "300221.SZ": ["2023-09", "2025-01"],
}


@skip_no_data
class TestMaTangleScreenRegression:
    @pytest.mark.parametrize("symbol,expected_date", list(EXPECTED_LATEST_MATCH.items()))
    def test_screen_latest_match_date(self, symbol, expected_date):
        dates = _screen_single(symbol)
        assert len(dates) == 1
        assert dates[0] == expected_date


@skip_no_data
class TestMaTangleEngineRegression:
    @pytest.mark.parametrize("symbol,expected_dates", list(EXPECTED_ALL_MATCH_DATES.items()))
    def test_engine_all_match_dates(self, symbol, expected_dates):
        result = _engine_backtest([symbol])
        assert symbol in result
        assert result[symbol] == expected_dates
