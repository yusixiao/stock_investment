from types import SimpleNamespace

import pandas as pd

from services.backtest import data_cache
from services.backtest.data_cache import MarketBundle


def test_old_loader_cannot_overwrite_new_generation():
    data_cache.invalidate("A")
    old_generation = data_cache.get_generation("A")
    data_cache.invalidate("A")
    new_generation = data_cache.get_generation("A")

    old_bundle = SimpleNamespace(symbols_count=1)
    new_bundle = SimpleNamespace(symbols_count=2)

    assert data_cache._publish_bundle_if_current(
        "A", old_generation, old_bundle
    ) is False
    assert data_cache.get_market("A") is None
    assert data_cache._publish_bundle_if_current(
        "A", new_generation, new_bundle
    ) is True
    assert data_cache.get_market("A") is new_bundle


def test_invalidate_keeps_previous_bundle_as_stale():
    data_cache.invalidate("A")
    generation = data_cache.get_generation("A")
    bundle = MarketBundle(market="A", stock_data={})
    assert data_cache._publish_bundle_if_current("A", generation, bundle)

    data_cache.invalidate("A")

    status = data_cache.get_status_all()["A"]
    assert status["loaded"] is True
    assert status["stale"] is True
    assert status["status"] == "stale"


def test_aggregate_and_compute_reuses_market_daily_container():
    daily = {
        "000001.SZ": pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=35),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": range(10, 45),
                "volume": 1000.0,
                "amount": 10000.0,
            }
        )
    }

    processed, weekly, monthly = data_cache._aggregate_and_compute(
        daily, data_cache.LoadProgress()
    )

    assert processed is daily
    assert "ma5" in daily["000001.SZ"]
    assert weekly["000001.SZ"].shape[0] > 0
    assert monthly["000001.SZ"].shape[0] > 0
