import json
import sqlite3

import pytest

from services.market_data.refresh_state import (
    RefreshAlreadyRunning,
    RefreshStateStore,
)


@pytest.fixture
def refresh_store(tmp_path):
    return RefreshStateStore(tmp_path / "refresh.db")


def test_start_refresh_rejects_when_one_is_running(refresh_store):
    first = refresh_store.start_refresh("manual")

    with pytest.raises(RefreshAlreadyRunning) as exc:
        refresh_store.start_refresh("scheduler")

    assert exc.value.refresh_id == first.refresh_id


def test_recent_records_keep_only_three_finished_refreshes(refresh_store):
    for _ in range(4):
        record = refresh_store.start_refresh("manual")
        refresh_store.finish_refresh(record.refresh_id, "completed")

    rows = refresh_store.get_recent()

    assert len(rows) == 3


def test_recover_interrupted_marks_running_refresh(refresh_store):
    record = refresh_store.start_refresh("scheduler")

    refresh_store.recover_interrupted()

    recovered = refresh_store.get_recent(limit=1)[0]
    assert recovered.refresh_id == record.refresh_id
    assert recovered.status == "interrupted"


def test_market_stage_records_are_independent(refresh_store):
    record = refresh_store.start_refresh("manual")

    refresh_store.record_market_stage(
        record.refresh_id, "A", "update", "success", {"updated": 10}
    )
    refresh_store.record_market_stage(
        record.refresh_id, "HK", "update", "failed", {"error": "rate limit"}
    )

    current = refresh_store.get(record.refresh_id)
    assert current.market_states["A"]["update"]["status"] == "success"
    assert current.market_states["HK"]["update"]["status"] == "failed"
    assert "US" not in current.market_states


def test_market_stage_detail_is_json_serializable(refresh_store):
    record = refresh_store.start_refresh("manual")

    refresh_store.record_market_stage(
        record.refresh_id, "US", "cache", "stale", {"generation": 4}
    )

    raw = sqlite3.connect(refresh_store.db_path).execute(
        "SELECT market_states FROM market_refreshes WHERE refresh_id = ?",
        (record.refresh_id,),
    ).fetchone()[0]
    assert json.loads(raw)["US"]["cache"]["detail"]["generation"] == 4
