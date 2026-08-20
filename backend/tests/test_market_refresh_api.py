from services.market_data.refresh_state import RefreshStateStore


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
