"""经营评述 — 数据模型(EastMoney F10 datacenter RPT_F10_OP_BUSINESSANALYSIS schema)。

D5 MD&A 维度数据源,2026-05-26 spike 验证(益丰药房 603939 实测 28 期):
- 年报 1.4-3.3k 字 / 中报 0.3-2.2k / 季报 0.1-0.7k
- BUSINESS_REVIEW 字段为已结构化纯文本,无需 PDF 解析

dedup key: REPORT_DATE(同一公司同期只保留一条)
extra='allow' 允许 EastMoney 后续新增字段。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class BusinessReviewRecord(BaseModel):
    """单期经营评述全文。"""

    model_config = ConfigDict(extra="allow")

    SECURITY_CODE: str
    REPORT_DATE: str  # YYYY-MM-DD
    REPORT_NAME: Optional[str] = None  # "2025年报" / "2024中报" / "2023一季报"
    BUSINESS_REVIEW: Optional[str] = None  # 全文
    SECURITY_NAME_ABBR: Optional[str] = None
