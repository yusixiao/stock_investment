"""定性分析数据模型(Pydantic)。

参数定义来自 cpa/prompts/references/factor_interface.md「定性参数」段落。
14 个结构化参数对应 6 维度叙事报告,Agent C 按 schema 校验完整性。

设计要点:
  - 必填 vs 可选区分严格(cycle_position / sotp_discount_pct 仅在适用时给值)
  - moat_rating 通用值域(强/较强/中/弱)→ 现金流保守策略值域(优质/中性/负面)映射
    单独函数 map_moat_rating_conservative 提供,Agent C 调用
  - DimensionReport 支持降级:narrative 标 ⚠️ + evidence 空时不阻塞
  - 全模型 Pydantic v2,model_dump_json / model_validate_json 双向可序列化
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ===== 枚举值域 =====
CapitalIntensity = Literal["capital-light", "capital-hungry"]
CollectionMode = Literal["先款后货", "订阅预收", "先货后款", "垫资回收"]
MoatRating = Literal["强", "较强", "中", "弱"]
Cyclicality = Literal["强周期", "弱周期", "非周期"]
CyclePosition = Literal["底部", "中段", "顶部"]
ManagementRating = Literal["优秀", "合格", "损害价值", "观察期"]
MdaCredibility = Literal["高", "中", "低"]
MdaImpact = Literal["正面", "中性", "负面"]

# 现金流保守策略值域(map_moat_rating_conservative 输出)
MoatRatingConservative = Literal["优质", "中性", "负面"]


class QualitativeParams(BaseModel):
    """6 维度结构化输出 — 14 参数。

    用于 Agent C 价值陷阱排查、安全边际周期修正、事件监控等下游消费。
    """

    # D1 商业模式
    capital_intensity: CapitalIntensity
    collection_mode: CollectionMode

    # D2 护城河
    moat_type: str
    moat_flywheel: bool
    moat_rating: MoatRating
    competitors: list[dict[str, Any]] = Field(default_factory=list)
    """[{name, ticker}] 主要竞争对手列表(Agent C 事件监控用)。"""

    # D3 行业周期
    cyclicality: Cyclicality
    cycle_position: Optional[CyclePosition] = None
    """仅在 cyclicality=强周期时填,Agent C 用于安全边际修正(底部 -1pct / 顶部 +2pct)。"""
    industry_keywords: list[str] = Field(default_factory=list)

    # D4 管理层
    management_rating: ManagementRating

    # D5 MD&A
    mda_credibility: MdaCredibility
    mda_impact: MdaImpact

    # D6 控股结构
    holding_structure: bool
    sotp_discount_pct: Optional[float] = None
    """仅在 holding_structure=True 时填(SOTP 折价率,0-1)。"""


class DimensionReport(BaseModel):
    """单维度报告:叙事 + 证据 + 该维度产出的部分参数。

    name: D1..D6
    title: 维度标题(如"商业模式与资本特征")
    narrative: 长文本论述(失败降级时以 ⚠️ 开头)
    evidence: 证据条目(数据点 / 引用来源 / 关键结论)
    """

    name: str
    title: str
    narrative: str
    evidence: list[str] = Field(default_factory=list)


class QualitativeReport(BaseModel):
    """完整定性分析报告 — 6 维度组合 + 末尾结构化参数表。

    持久化:json 落 data/qualitative/<code>_<name>/report_<YYYYMMDD>.json
    渲染:同时落 .md(Agent C / 用户阅读)
    """

    stock_code: str
    stock_name: str
    report_date: str
    """对应 §3 财务表最新 REPORT_DATE,用于缓存失效判定。"""

    dimensions: list[DimensionReport]
    params: QualitativeParams

    def get_dimension(self, name: str) -> Optional[DimensionReport]:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None


# ===== 值域映射 =====
_MOAT_RATING_CONSERVATIVE_MAP: dict[str, MoatRatingConservative] = {
    "强": "优质",
    "较强": "优质",
    "中": "中性",
    "弱": "负面",
}


def map_moat_rating_conservative(rating: str) -> MoatRatingConservative:
    """通用值域(强/较强/中/弱)→ 现金流保守策略值域(优质/中性/负面)。

    Agent C 在读取 qualitative_report.md 时执行此映射,
    见 factor_interface.md 「值域映射」段落。
    """
    if rating not in _MOAT_RATING_CONSERVATIVE_MAP:
        raise ValueError(f"unknown moat_rating: {rating!r}")
    return _MOAT_RATING_CONSERVATIVE_MAP[rating]
