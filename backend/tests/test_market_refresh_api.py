from services.market_data.refresh_state import RefreshStateStore


class _RefreshRecord:
    refresh_id = "refresh-123"


class _FakeRefreshRunner:
    calls = []

    def __init__(self):
        pass

    def start(self, *, source, markets):
        self.calls.append({"source": source, "markets": markets})
        return _RefreshRecord()


class _AlreadyRunningRefreshRunner:
    def __init__(self):
        pass

    def start(self, *, source, markets):
        from services.market_data.refresh_state import RefreshAlreadyRunning

        raise RefreshAlreadyRunning("refresh-123")


def test_refresh_progress_returns_active_and_recent(monkeypatch, tmp_path):
    store = RefreshStateStore(tmp_path / "refresh.db")
    record = store.start_refresh("manual")

    monkeypatch.setattr(
        "services.market_data.refresh_state.RefreshStateStore",
        lambda: store,
    )

    from routers.market_update import get_progress

    result = get_progress()

    assert result["active"]["refresh_id"] == record.refresh_id
    assert result["recent"][0]["source"] == "manual"


def test_refresh_progress_returns_recent_without_active(monkeypatch, tmp_path):
    store = RefreshStateStore(tmp_path / "refresh.db")
    record = store.start_refresh("scheduler")
    store.finish_refresh(record.refresh_id, "completed")

    monkeypatch.setattr(
        "services.market_data.refresh_state.RefreshStateStore",
        lambda: store,
    )

    from routers.market_update import get_progress

    result = get_progress()

    assert result["active"] is None
    assert result["recent"][0]["status"] == "completed"


def test_adjust_factor_trigger_starts_background_thread(monkeypatch):
    started = []

    class ImmediateThread:
        def __init__(self, target, args, **_kwargs):
            self.target = target
            self.args = args

        def start(self):
            started.append(self.args)
            self.target(*self.args)

    monkeypatch.setattr("routers.market_update.threading.Thread", ImmediateThread)
    monkeypatch.setattr(
        "services.market_data.updaters.market_updater.update_adjust_factors",
        lambda markets: {"A": 1} if markets == ["A"] else {},
    )

    from routers.market_update import UpdateRequest, trigger_adjust_factor

    result = trigger_adjust_factor(UpdateRequest(market="A"))

    assert result["markets"] == ["A"]
    assert started == [(["A"],)]


def test_manual_refresh_all_markets_uses_runner_and_response_contract(monkeypatch):
    _FakeRefreshRunner.calls = []
    monkeypatch.setattr(
        "services.market_data.refresh_runner.RefreshRunner", _FakeRefreshRunner
    )

    from routers.market_update import trigger_update

    result = trigger_update()

    assert _FakeRefreshRunner.calls == [{"source": "manual", "markets": None}]
    assert result == {
        "message": "Market refresh started",
        "market": "ALL",
        "refresh_id": "refresh-123",
    }


def test_manual_refresh_single_market_passes_selected_market(monkeypatch):
    _FakeRefreshRunner.calls = []
    monkeypatch.setattr(
        "services.market_data.refresh_runner.RefreshRunner", _FakeRefreshRunner
    )

    from routers.market_update import UpdateRequest, trigger_update

    result = trigger_update(UpdateRequest(market="HK"))

    assert _FakeRefreshRunner.calls == [{"source": "manual", "markets": ["HK"]}]
    assert result["market"] == "HK"
    assert result["refresh_id"] == "refresh-123"


def test_manual_refresh_normalizes_market_before_runner_and_response(monkeypatch):
    _FakeRefreshRunner.calls = []
    monkeypatch.setattr(
        "services.market_data.refresh_runner.RefreshRunner", _FakeRefreshRunner
    )

    from routers.market_update import UpdateRequest, trigger_update

    result = trigger_update(UpdateRequest(market=" hk "))

    assert _FakeRefreshRunner.calls == [{"source": "manual", "markets": ["HK"]}]
    assert result["market"] == "HK"


def test_manual_refresh_rejects_empty_or_whitespace_market(monkeypatch):
    _FakeRefreshRunner.calls = []
    monkeypatch.setattr(
        "services.market_data.refresh_runner.RefreshRunner", _FakeRefreshRunner
    )

    from fastapi import HTTPException
    from routers.market_update import UpdateRequest, trigger_update

    for market in ("", "   "):
        try:
            trigger_update(UpdateRequest(market=market))
        except HTTPException as exc:
            assert exc.status_code == 400
            assert exc.detail == f"Invalid market: {market}"
        else:
            raise AssertionError("empty market should raise HTTPException")

    assert _FakeRefreshRunner.calls == []


def test_manual_refresh_maps_already_running_to_conflict(monkeypatch):
    monkeypatch.setattr(
        "services.market_data.refresh_runner.RefreshRunner", _AlreadyRunningRefreshRunner
    )

    from fastapi import HTTPException
    from routers.market_update import trigger_update

    try:
        trigger_update()
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == {
            "message": "Market refresh already in progress",
            "refresh_id": "refresh-123",
        }
    else:
        raise AssertionError("already-running refresh should raise HTTPException")


def test_manual_refresh_rejects_invalid_market(monkeypatch):
    _FakeRefreshRunner.calls = []
    monkeypatch.setattr(
        "services.market_data.refresh_runner.RefreshRunner", _FakeRefreshRunner
    )

    from fastapi import HTTPException
    from routers.market_update import UpdateRequest, trigger_update

    try:
        trigger_update(UpdateRequest(market="JP"))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "Invalid market: JP"
    else:
        raise AssertionError("invalid market should raise HTTPException")

    assert _FakeRefreshRunner.calls == []
