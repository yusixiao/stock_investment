"""HK Eastmoney daily price contract regressions."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.models.event import DividendRecord
from backend.models.market import DailyKlineRecord
from services.market_data.updaters import market_updater as mu


def _kline(date: str, close: float, amount: float | None = None) -> DailyKlineRecord:
    return DailyKlineRecord(
        date=date,
        code="01969.HK",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100.0,
        amount=close * 100.0 if amount is None else amount,
    )


def test_transient_scale_spike_is_removed_but_persistent_scale_change_is_kept():
    from services.market_data.hk_price_cleaner import clean_transient_scale_spikes

    records = [
        {"date": "2025-01-09", "close": 4.24},
        {"date": "2025-01-10", "close": 423.0},
        {"date": "2025-01-13", "close": 4.28},
        {"date": "2025-01-14", "close": 42.8},
        {"date": "2025-01-15", "close": 43.1},
    ]

    cleaned = clean_transient_scale_spikes(records)

    assert [row["date"] for row in cleaned] == [
        "2025-01-09",
        "2025-01-13",
        "2025-01-14",
        "2025-01-15",
    ]


def test_cleaner_recomputes_derived_previous_close_after_removal():
    from services.market_data.hk_price_cleaner import clean_transient_scale_spikes

    first = _kline("2025-01-09", 4.24)
    spike = _kline("2025-01-10", 423.0)
    following = _kline("2025-01-13", 4.28)
    following.preclose = 423.0
    following.pctChg = (4.28 - 423.0) / 423.0 * 100

    cleaned = clean_transient_scale_spikes([first, spike, following])

    assert cleaned[-1].preclose == 4.24
    assert cleaned[-1].pctChg == pytest.approx((4.28 - 4.24) / 4.24 * 100)


def test_build_div_factor_adds_pre_event_baseline():
    from scripts.import_hk_eastmoney import build_div_factor

    dividends = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-03"]),
            "dividends": [1.0],
        }
    )
    close_map = {
        "2020-01-02": 100.0,
        "2020-01-03": 99.0,
        "2020-01-06": 99.5,
    }

    factors = build_div_factor(dividends, close_map)

    assert factors == [("2020-01-02", 0.99), ("2020-01-03", 1.0)]


def test_import_daily_records_use_eastmoney_amount():
    from scripts.import_hk_eastmoney import build_daily_records

    source = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02"]),
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close_raw": [10.5],
            "volume": [1000.0],
        }
    )

    records = build_daily_records(
        source,
        "00700.HK",
        {"2020-01-02": 12345.0},
    )

    assert records[0]["amount"] == 12345.0


def test_import_amount_fetch_uses_clean_fqt0_records():
    from scripts.import_hk_eastmoney import fetch_eastmoney_amounts

    adapter = MagicMock()
    adapter.fetch_daily_kline.return_value = [_kline("2020-01-02", 10.0, 12345.0)]
    source = pd.DataFrame({"date": pd.to_datetime(["2020-01-02"])})

    amounts = fetch_eastmoney_amounts(adapter, "00700.HK", source)

    adapter.fetch_daily_kline.assert_called_once_with(
        "00700.HK", "2020-01-02", "2020-01-02", fqt=0
    )
    assert amounts == {"2020-01-02": 12345.0}


def test_hk_incremental_update_overlaps_latest_and_filters_spike(monkeypatch):
    monkeypatch.setattr(mu, "_last_closed_trading_date", lambda market: "2025-01-13")
    monkeypatch.setitem(mu.THROTTLE_SEC_BY_MARKET, "HK", 0.0)

    adapter = MagicMock()
    adapter.fetch_daily_kline.return_value = [
        _kline("2025-01-09", 4.24),
        _kline("2025-01-10", 423.0),
        _kline("2025-01-13", 4.28),
    ]
    repo = MagicMock()
    repo.list_codes.return_value = ["01969.HK"]
    repo.get_latest_date.return_value = "2025-01-09"
    monkeypatch.setattr(mu, "_get_adapter", lambda market: adapter)
    monkeypatch.setattr(mu, "_get_repo", lambda market: repo)

    result = mu._update_market_kline("HK")

    assert result.updated == 1
    adapter.fetch_daily_kline.assert_called_once_with(
        "01969.HK", "2025-01-09", "2025-01-13"
    )
    written = repo.append_daily_kline.call_args.args[1]
    assert [row.date for row in written] == ["2025-01-09", "2025-01-13"]


def test_eastmoney_factor_has_pre_event_baseline(monkeypatch):
    adapter = EastMoneyAdapter()
    adapter.fetch_dividends = MagicMock(
        return_value=[
            DividendRecord(
                code="00700.HK",
                dividOperateDate="2020-01-03",
                dividCashPsBeforeTax=1.0,
            )
        ]
    )
    adapter.fetch_daily_kline = MagicMock(
        return_value=[
            _kline("2020-01-02", 100.0),
            _kline("2020-01-03", 99.0),
            _kline("2020-01-06", 99.5),
        ]
    )

    records = adapter.fetch_adjust_factor("00700.HK")

    assert [(r.dividOperateDate, r.foreAdjustFactor) for r in records] == [
        ("2020-01-02", 0.99),
        ("2020-01-03", 1.0),
    ]
