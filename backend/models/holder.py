"""§7 控股股东与管理层 — 数据模型(EastMoney F10 原始 schema)。

三张表对应三个 reportName(2026-05-24 spike 验证):
- Top10HolderRecord       ← RPT_F10_EH_HOLDERS
- Top10FreeHolderRecord   ← RPT_F10_EH_FREEHOLDERS
- HolderCountRecord       ← RPT_HOLDERNUMLATEST(单期 + PRE_END_DATE 上期对比)

extra='allow' 允许 EastMoney 后续新增字段直接落地,不破坏向后兼容。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class Top10HolderRecord(BaseModel):
    """十大股东(全部口径,含 H 股 / A 股)。dedup key:(END_DATE, HOLDER_RANK)"""

    model_config = ConfigDict(extra="allow")

    SECURITY_CODE: str
    END_DATE: str  # 报告期日(YYYY-MM-DD)
    HOLDER_RANK: int  # 排名 1-10
    HOLDER_NAME: Optional[str] = None
    HOLD_NUM: Optional[float] = None  # 持股数(股)
    HOLD_NUM_RATIO: Optional[float] = None  # 占总股本 %
    HOLD_NUM_CHANGE: Optional[str] = None  # 较上期变动股数(可能 "不变")
    CHANGE_RATIO: Optional[float] = None  # 较上期变动比例
    HOLDER_TYPE: Optional[str] = None
    SHARES_TYPE: Optional[str] = None  # 流通A股 / 流通H股 / 限售股
    HOLDER_STATEE: Optional[str] = None  # 加仓 / 减仓 / 不变
    HOLDER_MARKET_CAP: Optional[float] = None
    SECURITY_NAME_ABBR: Optional[str] = None


class Top10FreeHolderRecord(BaseModel):
    """十大流通股东。dedup key:(END_DATE, HOLDER_RANK)"""

    model_config = ConfigDict(extra="allow")

    SECURITY_CODE: str
    END_DATE: str
    HOLDER_RANK: int
    HOLDER_NAME: Optional[str] = None
    HOLD_NUM: Optional[float] = None
    HOLD_RATIO: Optional[float] = None  # 占总股本 %
    FREE_HOLDNUM_RATIO: Optional[float] = None  # 占流通股本 %
    HOLD_NUM_CHANGE: Optional[str] = None
    CHANGE_RATIO: Optional[float] = None
    HOLDER_TYPE: Optional[str] = None
    SHARES_TYPE: Optional[str] = None
    HOLDER_STATE: Optional[str] = None
    SECURITY_NAME_ABBR: Optional[str] = None


class HolderCountRecord(BaseModel):
    """股东户数(自带 PRE_HOLDER_NUM 上期对比)。dedup key:END_DATE"""

    model_config = ConfigDict(extra="allow")

    SECURITY_CODE: str
    END_DATE: str
    HOLDER_NUM: Optional[int] = None
    PRE_END_DATE: Optional[str] = None
    PRE_HOLDER_NUM: Optional[int] = None
    HOLDER_NUM_CHANGE: Optional[float] = None
    HOLDER_NUM_RATIO: Optional[float] = None  # 较上期变动 %
    AVG_HOLD_NUM: Optional[float] = None  # 户均持股数
    AVG_MARKET_CAP: Optional[float] = None  # 户均持股市值
    TOTAL_MARKET_CAP: Optional[float] = None
    HOLD_NOTICE_DATE: Optional[str] = None
    SECURITY_NAME_ABBR: Optional[str] = None
