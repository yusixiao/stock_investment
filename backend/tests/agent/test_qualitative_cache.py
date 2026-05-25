"""阶段 1.3 RED:Qualitative cache 测试。

覆盖:
- put / get 基础读写(json + md 双产物)
- 30 天 TTL:< 30 天命中,>= 30 天 miss
- REPORT_DATE 失效:DuckDB 中财务表 REPORT_DATE 推进时,旧缓存失效
- 缓存路径分离:按 stock_code 隔离,name 改了不影响命中
- _meta.json 含 ttl_until / report_date / sources
- 不存在的 code 返回 None
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.schema import (
    DimensionReport,
    QualitativeParams,
    QualitativeReport,
)


def _make_report(
    code="600519.SH", name="贵州茅台", report_date="2024-12-31"
) -> QualitativeReport:
    params = QualitativeParams(
        capital_intensity="capital-light",
        collection_mode="先款后货",
        moat_type="[非技术] 品牌",
        moat_flywheel=False,
        moat_rating="强",
        cyclicality="非周期",
        management_rating="合格",
        mda_credibility="高",
        mda_impact="正面",
        holding_structure=False,
    )
    dimensions = [
        DimensionReport(
            name=f"D{i}", title=f"维度{i}", narrative=f"d{i} narrative", evidence=[]
        )
        for i in range(1, 7)
    ]
    return QualitativeReport(
        stock_code=code,
        stock_name=name,
        report_date=report_date,
        dimensions=dimensions,
        params=params,
    )


class TestCacheBasic:
    def test_get_miss_returns_none(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        assert cache.get("000001.SZ", current_report_date="2024-12-31") is None

    def test_put_then_get_hit(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        report = _make_report()
        cache.put(report)
        loaded = cache.get("600519.SH", current_report_date="2024-12-31")
        assert loaded is not None
        assert loaded.stock_code == "600519.SH"
        assert loaded.params.moat_rating == "强"

    def test_put_writes_json_and_md(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        report = _make_report()
        cache.put(report)
        # 检查目录结构
        d = tmp_path / "600519.SH_贵州茅台"
        assert d.exists()
        # 应有 json + md + _meta.json
        jsons = list(d.glob("report_*.json"))
        mds = list(d.glob("report_*.md"))
        meta = d / "_meta.json"
        assert len(jsons) == 1
        assert len(mds) == 1
        assert meta.exists()

    def test_meta_contains_required_fields(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        report = _make_report()
        cache.put(report, sources=["tavily", "eastmoney"])
        meta_path = tmp_path / "600519.SH_贵州茅台" / "_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["report_date"] == "2024-12-31"
        assert "ttl_until" in meta
        assert meta["sources"] == ["tavily", "eastmoney"]
        # ttl_until 应为 put 时刻 + 30 天
        ttl_dt = datetime.fromisoformat(meta["ttl_until"])
        assert ttl_dt > datetime.now() + timedelta(days=29)
        assert ttl_dt < datetime.now() + timedelta(days=31)


class TestCacheTTL:
    def test_within_ttl_hits(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report())
        assert cache.get("600519.SH", current_report_date="2024-12-31") is not None

    def test_expired_ttl_misses(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report())
        # 手改 _meta.json 把 ttl_until 推到过去
        meta_path = tmp_path / "600519.SH_贵州茅台" / "_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["ttl_until"] = (datetime.now() - timedelta(days=1)).isoformat()
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        # TTL 过期 → miss
        assert cache.get("600519.SH", current_report_date="2024-12-31") is None


class TestCacheReportDateInvalidation:
    def test_same_report_date_hits(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report(report_date="2024-09-30"))
        assert cache.get("600519.SH", current_report_date="2024-09-30") is not None

    def test_newer_report_date_invalidates(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report(report_date="2024-09-30"))
        # DuckDB 中出现了更新的报告期 → miss
        assert cache.get("600519.SH", current_report_date="2024-12-31") is None

    def test_older_report_date_still_hits(self, tmp_path: Path):
        """current_report_date 比缓存里的旧(理论上不该发生),不失效。"""
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report(report_date="2024-12-31"))
        assert cache.get("600519.SH", current_report_date="2024-09-30") is not None

    def test_no_current_report_date_skips_check(self, tmp_path: Path):
        """current_report_date=None 时只看 TTL,不做报告期校验。"""
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report())
        assert cache.get("600519.SH", current_report_date=None) is not None


class TestCacheKeying:
    def test_different_codes_isolated(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report(code="600519.SH", name="贵州茅台"))
        cache.put(_make_report(code="000858.SZ", name="五粮液"))
        assert (
            cache.get("600519.SH", current_report_date="2024-12-31").stock_name
            == "贵州茅台"
        )
        assert (
            cache.get("000858.SZ", current_report_date="2024-12-31").stock_name
            == "五粮液"
        )

    def test_invalidate_removes_dir(self, tmp_path: Path):
        cache = QualitativeCache(tmp_path)
        cache.put(_make_report())
        d = tmp_path / "600519.SH_贵州茅台"
        assert d.exists()
        cache.invalidate("600519.SH")
        assert not d.exists()
        assert cache.get("600519.SH", current_report_date="2024-12-31") is None
