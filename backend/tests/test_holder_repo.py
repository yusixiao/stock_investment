"""§7 控股股东 repository 测试 — Top10/Top10Free/HolderCount 三表 roundtrip + 复合键去重。"""

from __future__ import annotations

import pytest

from backend.models.holder import (
    Top10HolderRecord,
    Top10FreeHolderRecord,
    HolderCountRecord,
)
from backend.repositories.holder_repo import HolderRepository


@pytest.fixture
def repo(tmp_path):
    return HolderRepository(tmp_path / "A" / "holders")


def _h(end_date, rank, name="X", num=100, ratio=1.0):
    return Top10HolderRecord(
        SECURITY_CODE="000001",
        END_DATE=end_date,
        HOLDER_RANK=rank,
        HOLDER_NAME=name,
        HOLD_NUM=num,
        HOLD_NUM_RATIO=ratio,
    )


def _fh(end_date, rank, name="X"):
    return Top10FreeHolderRecord(
        SECURITY_CODE="000001",
        END_DATE=end_date,
        HOLDER_RANK=rank,
        HOLDER_NAME=name,
        HOLD_NUM=100,
        HOLD_RATIO=1.0,
    )


def _hc(end_date, num=1000):
    return HolderCountRecord(
        SECURITY_CODE="000001",
        END_DATE=end_date,
        HOLDER_NUM=num,
    )


def test_top10_holders_roundtrip(repo):
    records = [_h("2026-03-31", 1, "A"), _h("2026-03-31", 2, "B")]
    repo.write_top10_holders("000001", records)
    got = repo.read_top10_holders("000001")
    assert len(got) == 2
    assert {r.HOLDER_NAME for r in got} == {"A", "B"}


def test_top10_holders_append_dedup_composite_key(repo):
    repo.write_top10_holders(
        "000001", [_h("2026-03-31", 1, "A"), _h("2026-03-31", 2, "B")]
    )
    # 同 (END_DATE, HOLDER_RANK) 的新记录覆盖旧记录;新 RANK=3 追加
    repo.append_top10_holders(
        "000001",
        [_h("2026-03-31", 1, "A_NEW"), _h("2026-03-31", 3, "C")],
    )
    got = repo.read_top10_holders("000001")
    assert len(got) == 3
    by_rank = {r.HOLDER_RANK: r.HOLDER_NAME for r in got}
    assert by_rank == {1: "A_NEW", 2: "B", 3: "C"}


def test_top10_holders_append_keeps_history_across_periods(repo):
    repo.write_top10_holders("000001", [_h("2025-12-31", 1, "A")])
    repo.append_top10_holders("000001", [_h("2026-03-31", 1, "A")])
    got = repo.read_top10_holders("000001")
    assert len(got) == 2
    assert {r.END_DATE for r in got} == {"2025-12-31", "2026-03-31"}


def test_top10_free_holders_roundtrip(repo):
    repo.write_top10_free_holders("000001", [_fh("2026-03-31", 1)])
    got = repo.read_top10_free_holders("000001")
    assert len(got) == 1


def test_holder_count_roundtrip_and_dedup(repo):
    repo.write_holder_count("000001", [_hc("2026-03-31", 100)])
    repo.append_holder_count("000001", [_hc("2026-03-31", 200), _hc("2025-12-31", 150)])
    got = repo.read_holder_count("000001")
    by_date = {r.END_DATE: r.HOLDER_NUM for r in got}
    assert by_date == {"2026-03-31": 200, "2025-12-31": 150}


def test_read_missing_returns_empty(repo):
    assert repo.read_top10_holders("999999") == []
    assert repo.read_top10_free_holders("999999") == []
    assert repo.read_holder_count("999999") == []


def test_write_empty_no_error(repo):
    repo.write_top10_holders("000001", [])
    repo.append_top10_holders("000001", [])
    assert repo.read_top10_holders("000001") == []
