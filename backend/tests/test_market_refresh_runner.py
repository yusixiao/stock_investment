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
        self.metadata = []

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

    def set_market_metadata(self, market, refresh_id, version, stale):
        self.metadata.append((market, refresh_id, version, stale))


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


def test_runner_default_auto_start_delegates_to_background_thread(
    monkeypatch, tmp_path, dependencies
):
    started = []

    class FakeThread:
        def __init__(self, target, args, **kwargs):
            self.target = target
            self.args = args
            self.kwargs = kwargs

        def start(self):
            started.append(self)

    monkeypatch.setattr(
        "services.market_data.refresh_runner.threading.Thread", FakeThread
    )
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
    )

    record = runner.start("manual", ["A"])

    assert len(started) == 1
    assert started[0].target == runner._run_background
    assert started[0].args == (record.refresh_id, ["A"])
    assert started[0].kwargs["daemon"] is True


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
        set_market_metadata=dependencies.set_market_metadata,
        auto_start=False,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    current = runner.store.get(record.refresh_id)
    detail = current.market_states["A"]["result"]["detail"]
    assert detail["market_version"] == 1
    assert dependencies.metadata == [("A", record.refresh_id, 1, False)]


def test_refreshes_duckdb_views_once_for_multiple_markets(tmp_path, dependencies):
    view_calls = []
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_views=lambda markets: view_calls.append(markets) or {"status": "success"},
        refresh_cache=dependencies.refresh_cache,
        auto_start=False,
    )

    record = runner.start("manual", ["A", "HK", "US"])
    runner.run(record.refresh_id, ["A", "HK", "US"])

    assert view_calls == [["A", "HK", "US"]]


def test_precache_return_value_limits_markets_entering_derived_stages(
    tmp_path, dependencies
):
    precache_calls = []
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        refresh_before_cache=lambda markets: precache_calls.append(markets) or ["A"],
        set_market_metadata=dependencies.set_market_metadata,
        auto_start=False,
    )

    record = runner.start("manual", ["A", "US"])
    runner.run(record.refresh_id, ["A", "US"])

    current = runner.store.get(record.refresh_id)
    assert precache_calls == [["A", "US"]]
    assert dependencies.loaded == ["A"]
    assert current.market_states["A"]["result"]["detail"]["cache_status"] == "ready"
    assert current.market_states["US"]["result"]["detail"]["stale"] is True
    assert "view" not in current.market_states["US"]
    assert "cache" not in current.market_states["US"]
    assert current.status == "partial"


def test_precache_failure_marks_successful_markets_stale_without_derived_stages(
    tmp_path, dependencies
):
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        refresh_before_cache=lambda markets: (_ for _ in ()).throw(
            RuntimeError("shares unavailable")
        ),
        set_market_metadata=dependencies.set_market_metadata,
        auto_start=False,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    current = runner.store.get(record.refresh_id)
    assert dependencies.loaded == []
    assert current.market_states["A"]["result"]["detail"]["stale"] is True
    assert dependencies.metadata == [("A", record.refresh_id, 0, True)]
    assert current.status == "partial"


def test_cache_failure_does_not_advance_market_version(tmp_path, dependencies):
    dependencies.refresh_cache = lambda market, refresh_id=None: {
        "status": "failed",
        "stale": True,
        "error": "load failed",
    }
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        set_market_metadata=dependencies.set_market_metadata,
        auto_start=False,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    current = runner.store.get(record.refresh_id)
    assert runner.store.get_market_version("A") == 0
    assert current.market_states["A"]["result"]["detail"]["stale"] is True
    assert dependencies.metadata == [("A", record.refresh_id, 0, True)]


def test_completion_callback_receives_final_refresh_record(tmp_path, dependencies):
    completed = []
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        set_market_metadata=dependencies.set_market_metadata,
        auto_start=False,
        on_complete=completed.append,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    assert len(completed) == 1
    assert completed[0].refresh_id == record.refresh_id
    assert completed[0].status == "completed"
    assert completed[0].finished_at is not None


def test_metadata_failure_does_not_change_ready_lifecycle(tmp_path, dependencies):
    def failing_metadata(*args):
        raise RuntimeError("metadata unavailable")

    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        set_market_metadata=failing_metadata,
        auto_start=False,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    current = runner.store.get(record.refresh_id)
    assert current.status == "completed"
    assert current.market_states["A"]["cache"]["status"] == "success"
    assert current.market_states["A"]["result"]["detail"]["cache_status"] == "ready"


def test_metadata_failure_does_not_block_stale_lifecycle(tmp_path, dependencies):
    dependencies.refresh_cache = lambda market, refresh_id=None: {
        "status": "failed",
        "stale": True,
        "error": "load failed",
    }

    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        set_market_metadata=lambda *args: (_ for _ in ()).throw(
            RuntimeError("metadata unavailable")
        ),
        auto_start=False,
    )

    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    current = runner.store.get(record.refresh_id)
    assert current.status == "partial"
    assert current.market_states["A"]["cache"]["status"] == "failed"
    assert current.market_states["A"]["result"]["detail"]["stale"] is True


def test_default_metadata_adapter_delegates_to_data_cache(tmp_path, dependencies, monkeypatch):
    metadata = []
    monkeypatch.setattr(
        data_cache,
        "set_market_metadata",
        lambda market, refresh_id, version, stale: metadata.append(
            (market, refresh_id, version, stale)
        ),
    )
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
    assert current.status == "completed"
    assert metadata == [("A", record.refresh_id, 1, False)]


def test_ready_market_finishes_before_metadata_is_published(tmp_path, dependencies):
    calls = []
    runner = RefreshRunner(
        tmp_path / "refresh.db",
        update_market=dependencies.update_market,
        refresh_view=dependencies.refresh_view,
        refresh_cache=dependencies.refresh_cache,
        set_market_metadata=lambda *args: calls.append("metadata"),
        auto_start=False,
    )
    original_finish_market = runner.store.finish_market

    def record_finish_market(*args, **kwargs):
        calls.append("finish_market")
        return original_finish_market(*args, **kwargs)

    runner.store.finish_market = record_finish_market
    record = runner.start("manual", ["A"])
    runner.run(record.refresh_id, ["A"])

    assert calls.index("finish_market") < calls.index("metadata")
