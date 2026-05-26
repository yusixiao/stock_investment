"""阶段 1.1 RED:Qualitative schema 测试。

覆盖:
- 14 个结构化参数的 Pydantic 序列化/反序列化
- 值域校验(enum 字段拒绝非法值)
- DimensionReport / QualitativeReport 组合
- moat_rating 通用值域 → cpa 现金流保守策略值域映射

不依赖外部数据源,纯模型测试。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.agent.core.qualitative.schema import (
    QualitativeParams,
    DimensionReport,
    QualitativeReport,
    map_moat_rating_conservative,
)


class TestQualitativeParams:
    """14 参数 Pydantic 模型测试。"""

    def test_minimal_valid_params(self):
        """最小合法集合:全部必填字段给值,可选字段缺省。"""
        p = QualitativeParams(
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
        assert p.capital_intensity == "capital-light"
        assert p.cycle_position is None  # 非强周期默认 None
        assert p.sotp_discount_pct is None
        assert p.competitors == []
        assert p.industry_keywords == []

    def test_strong_cycle_with_position(self):
        p = QualitativeParams(
            capital_intensity="capital-hungry",
            collection_mode="先货后款",
            moat_type="[非技术] 规模",
            moat_flywheel=True,
            moat_rating="较强",
            cyclicality="强周期",
            cycle_position="底部",
            management_rating="优秀",
            mda_credibility="中",
            mda_impact="中性",
            holding_structure=True,
            sotp_discount_pct=0.25,
            competitors=[
                {"name": "比亚迪", "ticker": "002594.SZ"},
                {"name": "蔚来", "ticker": "NIO"},
            ],
            industry_keywords=["新能源车", "电池"],
        )
        assert p.cycle_position == "底部"
        assert p.sotp_discount_pct == 0.25
        assert len(p.competitors) == 2
        assert p.competitors[0]["ticker"] == "002594.SZ"

    def test_invalid_capital_intensity_rejected(self):
        with pytest.raises(ValidationError):
            QualitativeParams(
                capital_intensity="middle",  # 非法,只允许 capital-light/hungry
                collection_mode="先款后货",
                moat_type="x",
                moat_flywheel=False,
                moat_rating="中",
                cyclicality="非周期",
                management_rating="合格",
                mda_credibility="中",
                mda_impact="中性",
                holding_structure=False,
            )

    def test_invalid_moat_rating_rejected(self):
        with pytest.raises(ValidationError):
            QualitativeParams(
                capital_intensity="capital-light",
                collection_mode="先款后货",
                moat_type="x",
                moat_flywheel=False,
                moat_rating="超级强",  # 非法
                cyclicality="非周期",
                management_rating="合格",
                mda_credibility="中",
                mda_impact="中性",
                holding_structure=False,
            )

    def test_invalid_management_rating_rejected(self):
        with pytest.raises(ValidationError):
            QualitativeParams(
                capital_intensity="capital-light",
                collection_mode="先款后货",
                moat_type="x",
                moat_flywheel=False,
                moat_rating="中",
                cyclicality="非周期",
                management_rating="完美",  # 非法
                mda_credibility="中",
                mda_impact="中性",
                holding_structure=False,
            )

    def test_round_trip_json(self):
        p = QualitativeParams(
            capital_intensity="capital-light",
            collection_mode="订阅预收",
            moat_type="[技术] 算法",
            moat_flywheel=True,
            moat_rating="强",
            cyclicality="弱周期",
            management_rating="优秀",
            mda_credibility="高",
            mda_impact="正面",
            holding_structure=False,
        )
        s = p.model_dump_json()
        p2 = QualitativeParams.model_validate_json(s)
        assert p2 == p


class TestMoatRatingMapping:
    """moat_rating 通用值域 → 现金流保守策略值域映射(Agent C 用)。"""

    def test_strong_maps_to_premium(self):
        assert map_moat_rating_conservative("强") == "优质"

    def test_relatively_strong_maps_to_premium(self):
        assert map_moat_rating_conservative("较强") == "优质"

    def test_medium_maps_to_neutral(self):
        assert map_moat_rating_conservative("中") == "中性"

    def test_weak_maps_to_negative(self):
        assert map_moat_rating_conservative("弱") == "负面"


class TestDimensionReport:
    def test_dimension_report_basic(self):
        d = DimensionReport(
            name="D2",
            title="竞争优势与护城河",
            narrative="公司在白酒高端市场占据 40% 份额...",
            evidence=["§3 毛利率 75%", "§7 大股东 5 年未减持"],
        )
        assert d.name == "D2"
        assert len(d.evidence) == 2

    def test_dimension_with_data_unavailable(self):
        """数据不可用降级:narrative 标 ⚠️,evidence 可空。"""
        d = DimensionReport(
            name="D5",
            title="MD&A 解读",
            narrative="⚠️ 数据不可用:未能获取历年 MD&A 文本",
            evidence=[],
        )
        assert d.narrative.startswith("⚠️")


class TestQualitativeReport:
    def test_full_report_assembly(self):
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
                name=f"D{i}", title=f"维度{i}", narrative="...", evidence=[]
            )
            for i in range(1, 7)
        ]
        report = QualitativeReport(
            stock_code="600519.SH",
            stock_name="贵州茅台",
            report_date="2024-12-31",
            dimensions=dimensions,
            params=params,
        )
        assert report.stock_code == "600519.SH"
        assert len(report.dimensions) == 6
        assert report.params.moat_rating == "强"

    def test_get_dimension_by_name(self):
        params = QualitativeParams(
            capital_intensity="capital-light",
            collection_mode="先款后货",
            moat_type="x",
            moat_flywheel=False,
            moat_rating="中",
            cyclicality="非周期",
            management_rating="合格",
            mda_credibility="中",
            mda_impact="中性",
            holding_structure=False,
        )
        d2 = DimensionReport(name="D2", title="护城河", narrative="X", evidence=[])
        report = QualitativeReport(
            stock_code="600519.SH",
            stock_name="茅台",
            report_date="2024-12-31",
            dimensions=[d2],
            params=params,
        )
        assert report.get_dimension("D2") is d2
        assert report.get_dimension("D9") is None

    def test_round_trip_json(self):
        params = QualitativeParams(
            capital_intensity="capital-hungry",
            collection_mode="垫资回收",
            moat_type="[非技术] 规模",
            moat_flywheel=True,
            moat_rating="较强",
            cyclicality="强周期",
            cycle_position="中段",
            management_rating="优秀",
            mda_credibility="高",
            mda_impact="正面",
            holding_structure=False,
            industry_keywords=["光伏", "硅料"],
        )
        report = QualitativeReport(
            stock_code="601012.SH",
            stock_name="隆基绿能",
            report_date="2024-12-31",
            dimensions=[
                DimensionReport(
                    name=f"D{i}", title=f"t{i}", narrative="n", evidence=["e"]
                )
                for i in range(1, 7)
            ],
            params=params,
        )
        s = report.model_dump_json()
        report2 = QualitativeReport.model_validate_json(s)
        assert report2.stock_code == report.stock_code
        assert report2.params.cycle_position == "中段"
        assert report2.params.industry_keywords == ["光伏", "硅料"]
