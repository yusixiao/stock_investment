import pandas as pd
import pytest

from services.backtest.data_cache import MarketBundle
from services.backtest.data_snapshot import create_snapshot
from services.backtest.engine import BacktestEngine
from services.backtest.strategy_base import Strategy


@pytest.fixture
def bundle() -> MarketBundle:
    frame = pd.DataFrame(
        {
            "date": ["2020-01-02", "2020-01-03", "2020-01-06"],
            "open": [10.0, 10.5, 11.0],
            "high": [10.5, 11.0, 11.5],
            "low": [9.5, 10.0, 10.5],
            "close": [10.2, 10.8, 11.2],
            "volume": [100.0, 110.0, 120.0],
        }
    )
    return MarketBundle(
        market="A",
        stock_data={"000001.SZ": frame, "000002.SZ": frame.copy()},
    )


def test_snapshot_reuses_bundle_dataframes(bundle: MarketBundle):
    snapshot = create_snapshot(
        bundle, "A", ["000001.SZ"], "2020-01-01", "2020-12-31"
    )

    assert snapshot.sliced.stock_data["000001.SZ"] is bundle.stock_data["000001.SZ"]
    assert snapshot.symbols == ("000001.SZ",)
    assert snapshot.sliced.iter_start_idx == 0
    assert snapshot.sliced.iter_end_idx == 2


def test_snapshot_contains_user_facing_data_context(bundle: MarketBundle):
    snapshot = create_snapshot(
        bundle,
        "A",
        None,
        None,
        None,
        generation=7,
        refresh_id="refresh-2026-08-20T075300.123456-a1b2c3d4",
        market_version=4,
        stale=True,
    )

    assert snapshot.data_context() == {
        "market": "A",
        "data_as_of": "2020-01-06",
        "stale": True,
    }
    assert snapshot.generation == 7
    assert snapshot.market_version == 4
    assert snapshot.refresh_id.endswith("a1b2c3d4")


def test_snapshot_rejects_missing_bundle():
    with pytest.raises(ValueError, match="bundle"):
        create_snapshot(None, "A", None, None, None)


def test_snapshot_rejects_empty_symbol_selection(bundle: MarketBundle):
    with pytest.raises(ValueError, match="stock data"):
        create_snapshot(bundle, "A", ["999999.SZ"], None, None)


def test_engine_accepts_snapshot_and_preserves_iteration_window(
    bundle: MarketBundle,
):
    snapshot = create_snapshot(bundle, "A", ["000001.SZ"], None, None)

    engine = BacktestEngine(
        strategy=Strategy(), snapshot=snapshot, enable_decision_log=False
    )

    assert engine._iter_start == snapshot.sliced.iter_start_idx
    assert engine._iter_end == snapshot.sliced.iter_end_idx


def test_engine_result_contains_data_context(bundle: MarketBundle):
    snapshot = create_snapshot(bundle, "A", None, None, None, stale=True)

    result = BacktestEngine(
        strategy=Strategy(), snapshot=snapshot, enable_decision_log=False
    ).run()

    assert result["data_context"]["data_as_of"] == snapshot.data_as_of
    assert result["data_context"]["stale"] is True


def test_snapshot_remains_bound_to_old_bundle_after_cache_invalidation(
    bundle: MarketBundle, monkeypatch
):
    from services.backtest import data_cache

    replacement = MarketBundle(
        market="A",
        stock_data={"000001.SZ": bundle.stock_data["000001.SZ"].copy()},
    )
    monkeypatch.setitem(data_cache._cache, "A", bundle)
    old_snapshot = create_snapshot(bundle, "A", None, None, None)
    old_generation = old_snapshot.generation

    data_cache.invalidate("A")
    monkeypatch.setitem(data_cache._cache, "A", replacement)
    new_snapshot = create_snapshot(replacement, "A", None, None, None)

    assert new_snapshot.generation == old_generation + 1
    assert old_snapshot.bundle is bundle
    assert old_snapshot.sliced.stock_data["000001.SZ"] is bundle.stock_data[
        "000001.SZ"
    ]
    assert new_snapshot.bundle is replacement
