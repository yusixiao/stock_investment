"""写入前数据完整性护栏 (A档「禁销毁」) 测试。

背景: 2026-07-02 一次财务重抓命中明细报表,INDUSTRY_NAME 整列变 null,
静默覆盖了磁盘上的好数据,导致数天无意义回测。本护栏在落盘前拦截这类
「用坏数据覆盖好数据」的写入。

A档规则:
- 台账型(ledger): 已存在 key 的行,旧非空→新 null = 违规; 整列消失 = 违规;
  行数灾难性骤减 = 违规。放行 新增行 / null→有值回填 / 非空→不同非空(盘中→收盘)。
- 重算型(recompute): 历史值可合法重算(如复权因子归一化),只查 整列消失 + 行数骤减。
- 违规 → 记录+告警,然后 raise DataIntegrityError; force=True 逃生阀放行并留痕。
"""

from typing import Optional

import pandas as pd
import pytest
from pydantic import BaseModel

from backend.repositories.base import (
    DataIntegrityError,
    IntegrityPolicy,
    append_models_to_parquet,
    check_write_integrity,
    read_integrity_violations,
    write_models_as_parquet,
)


@pytest.fixture(autouse=True)
def _redirect_integrity_log(tmp_path, monkeypatch):
    """把默认告警落地目录重定向到 tmp, 防止未显式传 record_dir 的用例
    污染真实 logs/data_integrity.jsonl。"""
    import backend.config as cfg

    monkeypatch.setattr(cfg, "LOG_DIR", tmp_path / "default_logs", raising=False)


def _write(path, rows):
    pd.DataFrame(rows).to_parquet(path, index=False)


class TestLedgerAllow:
    """台账型:合法写入必须放行(零误报)。"""

    def test_first_write_allowed(self, tmp_path):
        # 文件不存在 → 无基线 → 放行
        p = tmp_path / "000001.SZ.parquet"
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        check_write_integrity(p, new, key="REPORT_DATE", mode="ledger")

    def test_new_key_rows_allowed(self, tmp_path):
        # 新增报告期(新 key) → 放行
        p = tmp_path / "a.parquet"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        new = pd.DataFrame(
            [
                {"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"},
                {"REPORT_DATE": "2026-03-31", "INDUSTRY_NAME": "铁路公路"},
            ]
        )
        check_write_integrity(p, new, key="REPORT_DATE", mode="ledger")

    def test_null_backfill_allowed(self, tmp_path):
        # 旧 null → 新有值(回填/富化,正是 07-02 修复动作本身) → 放行
        p = tmp_path / "a.parquet"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": None}])
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        check_write_integrity(p, new, key="REPORT_DATE", mode="ledger")

    def test_nonnull_to_different_nonnull_allowed(self, tmp_path):
        # 盘中 partial bar → 收盘完整 bar(非空→不同非空) → 放行
        p = tmp_path / "a.parquet"
        _write(p, [{"date": "2026-05-13", "close": 10.0}])
        new = pd.DataFrame([{"date": "2026-05-13", "close": 10.5}])
        check_write_integrity(p, new, key="date", mode="ledger")

    def test_identical_rewrite_allowed(self, tmp_path):
        p = tmp_path / "a.parquet"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        check_write_integrity(p, new, key="REPORT_DATE", mode="ledger")


class TestLedgerBlock:
    """台账型:销毁已有数据必须拦截。"""

    def test_nonnull_to_null_raises_0702_repro(self, tmp_path):
        # 07-02 复现: 历史行的非空 INDUSTRY_NAME 被覆盖成 null
        p = tmp_path / "a.parquet"
        _write(
            p,
            [
                {"REPORT_DATE": "2015-12-31", "INDUSTRY_NAME": "铁路公路"},
                {"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"},
            ],
        )
        new = pd.DataFrame(
            [
                {"REPORT_DATE": "2015-12-31", "INDUSTRY_NAME": None},
                {"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": None},
            ]
        )
        with pytest.raises(DataIntegrityError) as ei:
            check_write_integrity(p, new, key="REPORT_DATE", mode="ledger")
        assert "INDUSTRY_NAME" in str(ei.value)

    def test_column_dropped_raises(self, tmp_path):
        # 整列消失(旧有 INDUSTRY_NAME 列,新数据没这列)
        p = tmp_path / "a.parquet"
        _write(
            p,
            [
                {
                    "REPORT_DATE": "2025-12-31",
                    "INDUSTRY_NAME": "铁路公路",
                    "TOTAL_ASSETS": 1.0,
                }
            ],
        )
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "TOTAL_ASSETS": 1.0}])
        with pytest.raises(DataIntegrityError) as ei:
            check_write_integrity(p, new, key="REPORT_DATE", mode="ledger")
        assert "INDUSTRY_NAME" in str(ei.value)

    def test_composite_key_null_raises(self, tmp_path):
        # 复合键(股东表 END_DATE + HOLDER_RANK)
        p = tmp_path / "a.parquet"
        _write(
            p,
            [{"END_DATE": "2025-12-31", "HOLDER_RANK": 1, "HOLDER_NAME": "香港中央结算"}],
        )
        new = pd.DataFrame(
            [{"END_DATE": "2025-12-31", "HOLDER_RANK": 1, "HOLDER_NAME": None}]
        )
        with pytest.raises(DataIntegrityError):
            check_write_integrity(
                p, new, key=["END_DATE", "HOLDER_RANK"], mode="ledger"
            )

    def test_row_count_catastrophic_drop_raises(self, tmp_path):
        # 行数骤减(20 → 1,低于 0.5 阈值)
        p = tmp_path / "a.parquet"
        _write(p, [{"date": f"2026-01-{i:02d}", "close": 10.0} for i in range(1, 21)])
        new = pd.DataFrame([{"date": "2026-01-01", "close": 10.0}])
        with pytest.raises(DataIntegrityError):
            check_write_integrity(p, new, key="date", mode="ledger")

    def test_force_bypasses(self, tmp_path):
        # force=True → 明知违规也放行(留痕,不 raise)
        p = tmp_path / "a.parquet"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": None}])
        check_write_integrity(
            p,
            new,
            key="REPORT_DATE",
            mode="ledger",
            force=True,
            record_dir=tmp_path / "logs",
        )


class TestRecompute:
    """重算型:历史值合法变动放行,仅结构护栏。"""

    def test_recompute_allows_value_change_and_null(self, tmp_path):
        # 复权因子归一化: 每逢新除权,历史 foreAdjustFactor 全部重算
        p = tmp_path / "a.parquet"
        _write(
            p,
            [
                {"dividOperateDate": "2024-06-15", "foreAdjustFactor": 1.1},
                {"dividOperateDate": "2025-07-01", "foreAdjustFactor": 1.0},
            ],
        )
        new = pd.DataFrame(
            [
                {"dividOperateDate": "2024-06-15", "foreAdjustFactor": 0.9},
                {"dividOperateDate": "2025-07-01", "foreAdjustFactor": 0.95},
                {"dividOperateDate": "2026-03-01", "foreAdjustFactor": 1.0},
            ]
        )
        check_write_integrity(p, new, key="dividOperateDate", mode="recompute")

    def test_recompute_column_dropped_raises(self, tmp_path):
        p = tmp_path / "a.parquet"
        _write(
            p,
            [
                {
                    "dividOperateDate": "2024-06-15",
                    "foreAdjustFactor": 1.1,
                    "backAdjustFactor": 2.0,
                }
            ],
        )
        new = pd.DataFrame(
            [{"dividOperateDate": "2024-06-15", "foreAdjustFactor": 1.1}]
        )
        with pytest.raises(DataIntegrityError):
            check_write_integrity(p, new, key="dividOperateDate", mode="recompute")


class TestAlerting:
    """违规必须记录到可查的 JSONL(健康端点数据源)。"""

    def test_violation_recorded_to_jsonl(self, tmp_path):
        p = tmp_path / "a.parquet"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": None}])
        rec_dir = tmp_path / "logs"
        with pytest.raises(DataIntegrityError):
            check_write_integrity(
                p, new, key="REPORT_DATE", mode="ledger", record_dir=rec_dir
            )
        jsonl = rec_dir / "data_integrity.jsonl"
        assert jsonl.exists()
        content = jsonl.read_text().strip()
        assert "INDUSTRY_NAME" in content
        assert "value_nulled" in content

    def test_no_violation_no_record(self, tmp_path):
        p = tmp_path / "a.parquet"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        rec_dir = tmp_path / "logs"
        check_write_integrity(
            p, new, key="REPORT_DATE", mode="ledger", record_dir=rec_dir
        )
        assert not (rec_dir / "data_integrity.jsonl").exists()


class TestReadViolations:
    """健康端点数据源: read_integrity_violations 聚合。"""

    def test_empty_when_no_file(self, tmp_path):
        r = read_integrity_violations(record_dir=tmp_path / "logs")
        assert r["total"] == 0 and r["blocked"] == 0 and r["recent"] == []

    def test_aggregates_blocked_and_forced(self, tmp_path):
        p = tmp_path / "a.parquet"
        rec_dir = tmp_path / "logs"
        _write(p, [{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": "铁路公路"}])
        new = pd.DataFrame([{"REPORT_DATE": "2025-12-31", "INDUSTRY_NAME": None}])
        # 一次被拦(raise) + 一次 force 放行
        with pytest.raises(DataIntegrityError):
            check_write_integrity(
                p, new, key="REPORT_DATE", mode="ledger", record_dir=rec_dir
            )
        check_write_integrity(
            p, new, key="REPORT_DATE", mode="ledger", force=True, record_dir=rec_dir
        )
        r = read_integrity_violations(record_dir=rec_dir)
        assert r["total"] == 2
        assert r["blocked"] == 1
        assert r["forced"] == 1
        assert r["recent_24h"] == 2
        assert r["latest_ts"] is not None


class _Row(BaseModel):
    """测试用最小模型(extra=allow 模拟 INDUSTRY_NAME 这类携带字段)。"""

    model_config = {"extra": "allow"}

    REPORT_DATE: str
    INDUSTRY_NAME: Optional[str] = None


class TestWriterWiring:
    """护栏经 write_/append_models_as_parquet opt-in 接入的端到端行为。"""

    def test_write_default_off_allows_destructive(self, tmp_path):
        # integrity=None(默认)→ 护栏关闭 → 破坏性覆盖照常写(向后兼容,零影响)
        p = tmp_path / "a.parquet"
        write_models_as_parquet(
            p, [_Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME="铁路公路")],
            sort_by="REPORT_DATE",
        )
        write_models_as_parquet(
            p, [_Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME=None)],
            sort_by="REPORT_DATE",
        )
        assert pd.read_parquet(p).iloc[0]["INDUSTRY_NAME"] is None

    def test_write_integrity_on_blocks(self, tmp_path):
        # opt-in 后, 整覆盖抹掉历史非空 → 拦截
        p = tmp_path / "a.parquet"
        write_models_as_parquet(
            p, [_Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME="铁路公路")],
            sort_by="REPORT_DATE",
        )
        with pytest.raises(DataIntegrityError):
            write_models_as_parquet(
                p, [_Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME=None)],
                sort_by="REPORT_DATE",
                integrity=IntegrityPolicy(
                    key="REPORT_DATE", record_dir=tmp_path / "logs"
                ),
            )
        # 拦截后磁盘仍是好数据(未被覆盖)
        assert pd.read_parquet(p).iloc[0]["INDUSTRY_NAME"] == "铁路公路"

    def test_append_retained_rows_no_false_positive(self, tmp_path):
        # append 新增报告期, 旧行原样保留 → 去重全集比对不误报
        p = tmp_path / "a.parquet"
        write_models_as_parquet(
            p,
            [
                _Row(REPORT_DATE="2024-12-31", INDUSTRY_NAME="铁路公路"),
                _Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME="铁路公路"),
            ],
            sort_by="REPORT_DATE",
        )
        append_models_to_parquet(
            p,
            [_Row(REPORT_DATE="2026-03-31", INDUSTRY_NAME="铁路公路")],
            _Row,
            dedup_key="REPORT_DATE",
            sort_by="REPORT_DATE",
            integrity=IntegrityPolicy(key="REPORT_DATE", record_dir=tmp_path / "logs"),
        )
        assert len(pd.read_parquet(p)) == 3

    def test_append_blocks_null_overwrite(self, tmp_path):
        # append 用 null 覆盖已存在 key 的非空 → 拦截(07-02 的 append 写路)
        p = tmp_path / "a.parquet"
        write_models_as_parquet(
            p, [_Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME="铁路公路")],
            sort_by="REPORT_DATE",
        )
        with pytest.raises(DataIntegrityError):
            append_models_to_parquet(
                p,
                [_Row(REPORT_DATE="2025-12-31", INDUSTRY_NAME=None)],
                _Row,
                dedup_key="REPORT_DATE",
                sort_by="REPORT_DATE",
                integrity=IntegrityPolicy(
                    key="REPORT_DATE", record_dir=tmp_path / "logs"
                ),
            )
