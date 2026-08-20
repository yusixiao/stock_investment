from types import SimpleNamespace

import pytest

from services.backtest import data_cache
from services.market_data.refresh_runner import RefreshRunner
from services.market_data.refresh_state import RefreshAlreadyRunning


class FakeRefreshDependencies:
    def __init__(self):
        self.fail_markets = set()
        self.invalidated = []
        self.loaded = []

    def update_market(self, market):
        if market in self.fail_markets:
            raise RuntimeError(f"{market} unavailable")
        return SimpleNamespace(updated=3, skipped=1, failed=0, aborted=False)

    def refresh_view(self, market):
        return {"status": "success"}

    def refresh_cache(self, market, refresh_id=None):
        self.invalidated.append(market)
        self.loaded.append(market)
        return {"status": "ready", "stale": False, "generation": 1}


@pytest.fixture
def dependencies():
    return FakeRefreshDependencies()


def test_runner_rejects_second_refresh_while_first_is_running(tmp_path, dependencies):
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        auto_start=False,
    )
    first = runner.start("manual", ["A", "HK", "US"])

    with pytest.raises(RefreshAlreadyRunning) as exc:
        runner.start("scheduler", ["A"])

    assert exc.value.refresh_id == first.refresh_id


def test_one_market_failure_does_not_fail_other_markets(tmp_path, dependencies):
    dependencies.fail_markets = {"HK"}
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        auto_start=False,
    )

    record = runner.start("scheduler", ["A", "HK", "US"])
    runner.run(record.refresh_id, ["A", "HK", "US"])

    current = runner.store.get(record.refresh_id)
    assert current.status == "partial"
    assert current.market_states["A"]["result"]["detail"]["cache_status"] == "ready"
    assert current.market_states["HK"]["result"]["detail"]["stale"] is True
    assert current.market_states["US"]["result"]["detail"]["cache_status"] == "ready"


def test_successful_market_advances_its_version(tmp_path, dependencies):
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        auto_start=False,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    current = runner.store.get(record.refresh_id)
    detail = current.market_states["A"]["result"]["detail"]
    assert detail["market_version"] == 1
    cache_status = data_cache.get_status("A")
    assert cache_status["market_version"] == 1
    assert cache_status["refresh_id"] == record.refresh_id
