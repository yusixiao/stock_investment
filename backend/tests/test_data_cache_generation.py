from types import SimpleNamespace

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
