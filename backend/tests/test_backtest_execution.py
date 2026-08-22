from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.backtest import execution


class FakeStrategy:
    name = "Fake strategy"
    frequency = "daily"
    params = {}

    def __init__(self, param_overrides=None):
        self.param_overrides = param_overrides or {}


class FakeEngine:
    last_kwargs = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).last_kwargs = kwargs

    def run(self):
        callback = self.kwargs.get("on_progress")
        if callback:
            callback(3, 10, "回测中...")
        return {"metrics": {"total_return": 0.25}, "trades": ["full"]}

    def run_scan(self):
        return {
            "events": {"000001.SZ": [("2026-08-21", {})]},
            "dates": ["2026-08-21"],
            "all_symbols_count": 1,
        }


@dataclass
class FakeTaskManager:
    created: list[tuple] 
    completed: list[tuple]
    failed: list[tuple]
    progress: list[tuple] | None = None

    def __post_init__(self):
        self.progress = self.progress or []

    def create_task(self, **kwargs):
        self.created.append(kwargs)
        return "task-1"

    def complete_task(self, task_id, result):
        self.completed.append((task_id, result))

    def fail_task(self, task_id, error):
        self.failed.append((task_id, error))

    def update_progress(self, task_id, current, total, phase=""):
        self.progress.append((task_id, current, total, phase))


@pytest.fixture
def spec():
    return execution.ExecutionSpec(
        mode=execution.ExecutionMode.SCAN,
        filepath=Path("fake_strategy.py"),
        strategy_class="FakeStrategy",
        market="A",
        symbols=["000001.SZ"],
        start_date="2026-08-21",
        end_date="2026-08-21",
        lookback_used="182d",
    )


def _patch_adapters(monkeypatch):
    monkeypatch.setattr(execution, "load_strategy_from_file", lambda path: [FakeStrategy])
    monkeypatch.setattr(execution.data_cache, "get_market", lambda market: "bundle")
    monkeypatch.setattr(execution, "create_snapshot", lambda *args, **kwargs: "snapshot")
    monkeypatch.setattr(execution, "BacktestEngine", FakeEngine)


def test_execution_spec_normalizes_mode_and_defaults():
    spec = execution.ExecutionSpec(
        mode="full",
        filepath="strategy.py",
        strategy_class="Example",
    )

    assert spec.mode is execution.ExecutionMode.FULL
    assert spec.filepath == Path("strategy.py")
    assert spec.params == {}
    assert spec.market == "A"


def test_execution_spec_preserves_strategy_metadata_and_task_source():
    spec = execution.ExecutionSpec(
        mode="scan",
        filepath="strategy.py",
        strategy_class="Example",
        strategy_name="Example strategy",
        frequency="weekly",
        task_type="monitor",
        trigger_source="monitor",
    )

    assert spec.strategy_name == "Example strategy"
    assert spec.frequency == "weekly"
    assert spec.task_type == "monitor"
    assert spec.trigger_source == "monitor"


@pytest.mark.parametrize(
    ("mode", "method", "expected"),
    [
        (execution.ExecutionMode.FULL, "run", {"metrics": {"x": 1}}),
    ],
)
def test_execute_dispatches_mode_without_changing_engine_payload(
    monkeypatch, spec, mode, method, expected
):
    _patch_adapters(monkeypatch)
    spec = execution.ExecutionSpec(**{**spec.__dict__, "mode": mode})

    class EngineWithPayload(FakeEngine):
        def run(self):
            return expected

        def run_scan(self):
            return expected

    monkeypatch.setattr(execution, "BacktestEngine", EngineWithPayload)

    result = execution.execute_backtest(spec)

    assert result is expected


def test_submit_creates_task_before_strategy_validation_and_persists_failure(monkeypatch, spec):
    manager = FakeTaskManager([], [], [])
    calls = []

    def missing_strategy(_path):
        calls.append("validate")
        raise FileNotFoundError("missing strategy")

    monkeypatch.setattr(execution, "load_strategy_from_file", missing_strategy)

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            calls.append("start")
            self.target()

    monkeypatch.setattr(execution.threading, "Thread", FakeThread)

    task_id = execution.submit_backtest(spec, task_manager=manager)

    assert task_id == "task-1"
    assert calls == ["start", "validate"]
    assert manager.created[0]["task_type"] == "scan-radar"
    assert manager.failed == [("task-1", "missing strategy")]


def test_submit_monitor_scan_persists_monitor_metadata(monkeypatch, spec):
    manager = FakeTaskManager([], [], [])
    spec.task_type = "monitor"
    spec.trigger_source = "monitor"
    spec.strategy_name = "Fake strategy"
    spec.frequency = "weekly"

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(execution.threading, "Thread", FakeThread)
    monkeypatch.setattr(execution, "execute_backtest", lambda *args, **kwargs: {"hits": []})

    execution.submit_backtest(spec, task_manager=manager)

    assert manager.created == [{
        "task_type": "monitor",
        "trigger_source": "monitor",
        "strategy_class": "FakeStrategy",
        "strategy_name": "Fake strategy",
        "params": {},
        "frequency": "weekly",
        "symbols": ["000001.SZ"],
        "market": "A",
        "start_date": "2026-08-21",
        "end_date": "2026-08-21",
        "log_dir": str(execution.LOG_DIR / "backtest"),
    }]


def test_submit_monitor_scan_persists_finalized_public_result(monkeypatch, spec):
    manager = FakeTaskManager([], [], [])
    spec.task_type = "monitor"
    spec.trigger_source = "monitor"
    spec.strategy_name = "Fake strategy"
    spec.frequency = "daily"
    frame = __import__("pandas").DataFrame(
        {"date": ["2026-08-21"], "close": [12.5]}
    )
    snapshot = SimpleNamespace(
        sliced=SimpleNamespace(stock_data={"000001.SZ": frame}),
        data_context=lambda: {"market": "A", "data_as_of": "2026-08-21", "stale": False},
        refresh_id="refresh-1",
        generation=3,
        market_version=7,
    )
    monkeypatch.setattr(execution, "load_strategy_from_file", lambda path: [FakeStrategy])
    monkeypatch.setattr(execution.data_cache, "get_market", lambda market: SimpleNamespace(
        stock_data={"000001.SZ": frame}, last_date="2026-08-21"
    ))
    monkeypatch.setattr(execution.data_cache, "get_status", lambda market: {})
    monkeypatch.setattr(execution, "create_snapshot", lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(execution, "BacktestEngine", FakeEngine)

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(execution.threading, "Thread", FakeThread)
    execution.submit_backtest(spec, task_manager=manager)

    assert manager.completed, manager.failed
    result = manager.completed[0][1]
    assert result["hits"][0]["symbol"] == "000001.SZ"
    assert result["total_scanned"] == 1
    assert result["date_range"] == {"start": "2026-08-21", "end": "2026-08-21"}
    assert result["lookback_used"] == "182d"
    assert result["strategy_name"] == "Fake strategy"
    assert result["frequency"] == "daily"
    assert result["data_context"]["market"] == "A"
    assert result["data_provenance"] == {
        "refresh_id": "refresh-1", "generation": 3, "market_version": 7
    }


def test_submit_persists_completion(monkeypatch, spec):
    manager = FakeTaskManager([], [], [])
    _patch_adapters(monkeypatch)
    spec = execution.ExecutionSpec(**{**spec.__dict__, "mode": execution.ExecutionMode.FULL})

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(execution.threading, "Thread", FakeThread)

    execution.submit_backtest(spec, task_manager=manager)

    assert manager.completed == [("task-1", {"metrics": {"total_return": 0.25}, "trades": ["full"]})]
    assert manager.failed == []


def test_submit_uses_route_log_dir_for_task_metadata_and_engine(monkeypatch, spec):
    manager = FakeTaskManager([], [], [])
    log_dir = Path("logs/scan_radar/task-1")
    spec.log_dir = log_dir
    _patch_adapters(monkeypatch)

    class FakeThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(execution.threading, "Thread", FakeThread)
    execution.submit_backtest(spec, task_manager=manager)

    assert manager.created[0]["log_dir"] == str(log_dir)
    assert execution.BacktestEngine.last_kwargs["log_dir"] == log_dir / "task-1"


def test_execute_forwards_progress_phase_to_task_manager(monkeypatch, spec):
    manager = FakeTaskManager([], [], [])
    _patch_adapters(monkeypatch)
    spec = execution.ExecutionSpec(**{**spec.__dict__, "mode": execution.ExecutionMode.FULL})

    class EngineWithProgress(FakeEngine):
        last_kwargs = None

        def __init__(self, **kwargs):
            type(self).last_kwargs = kwargs
            super().__init__(**kwargs)

    monkeypatch.setattr(execution, "BacktestEngine", EngineWithProgress)
    execution.execute_backtest(spec, task_id="task-1", task_manager=manager)

    assert manager.progress[0] == ("task-1", 0, 0, "切片数据中...")
    assert manager.progress[-1] == ("task-1", 3, 10, "回测中...")
