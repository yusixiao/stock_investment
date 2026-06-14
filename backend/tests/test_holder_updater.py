"""§7 控股股东 — HolderUpdater 缓存测试(7 天 TTL + 失败降级)。"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.models.holder import Top10HolderRecord, HolderCountRecord
from backend.repositories.holder_repo import HolderRepository
from backend.services.market_data.updaters.holder_updater import HolderUpdater


@pytest.fixture
def updater(tmp_path):
    repo = HolderRepository(tmp_path / "holders")
    return HolderUpdater(repo=repo, ttl_days=7)


def _h(rank=1, name="A", end_date="2026-03-31"):
    return Top10HolderRecord(
        SECURITY_CODE="000001",
        END_DATE=end_date,
        HOLDER_RANK=rank,
        HOLDER_NAME=name,
        HOLD_NUM=100,
        HOLD_NUM_RATIO=1.0,
    )


def test_first_call_fetches_and_caches(updater):
    with patch.object(updater, "_fetch_remote", return_value=[_h(1), _h(2)]) as mock:
        out = updater.fetch_with_cache("000001", "top10")
    assert len(out) == 2
    assert mock.call_count == 1


def test_second_call_within_ttl_uses_cache(updater):
    with patch.object(updater, "_fetch_remote", return_value=[_h(1)]) as mock:
        updater.fetch_with_cache("000001", "top10")
        updater.fetch_with_cache("000001", "top10")
    assert mock.call_count == 1


def test_expired_cache_refetches(updater, tmp_path):
    with patch.object(updater, "_fetch_remote", return_value=[_h(1)]):
        updater.fetch_with_cache("000001", "top10")

    # 把 parquet mtime 改成 8 天前
    p = tmp_path / "holders" / "top10" / "000001.parquet"
    assert p.exists()
    old = time.time() - 8 * 86400
    import os

    os.utime(p, (old, old))

    with patch.object(updater, "_fetch_remote", return_value=[_h(2)]) as mock:
        out = updater.fetch_with_cache("000001", "top10")
    assert mock.call_count == 1
    # append + dedup 后应有 2 条
    assert len(out) == 2


def test_remote_failure_falls_back_to_existing(updater, tmp_path):
    with patch.object(updater, "_fetch_remote", return_value=[_h(1)]):
        updater.fetch_with_cache("000001", "top10")

    p = tmp_path / "holders" / "top10" / "000001.parquet"
    old = time.time() - 8 * 86400
    import os

    os.utime(p, (old, old))

    with patch.object(updater, "_fetch_remote", side_effect=RuntimeError("net")):
        out = updater.fetch_with_cache("000001", "top10")
    assert len(out) == 1


def test_holder_count_table(updater):
    rec = HolderCountRecord(
        SECURITY_CODE="000001", END_DATE="2026-03-31", HOLDER_NUM=1000
    )
    with patch.object(updater, "_fetch_remote", return_value=[rec]):
        out = updater.fetch_with_cache("000001", "holder_count")
    assert len(out) == 1
    assert out[0].HOLDER_NUM == 1000


def test_unknown_table_raises(updater):
    with pytest.raises(ValueError):
        updater.fetch_with_cache("000001", "unknown_table")
