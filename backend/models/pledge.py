"""§7 股权质押 — 中证登周频快照数据模型。

数据源(2026-05-26 spike 验证):
- EastMoney datacenter API,reportName = `RPT_CSDC_LIST`
- 周频(每周五),A 股全样本,茅台 2014 至今 ~586 条

字段语义:
- TRADE_DATE — 周快照日期(YYYY-MM-DD HH:MM:SS)
- PLEDGE_RATIO — 质押占总股本比例(%);> 50% 即高风险
- REPURCHASE_BALANCE — 待购回余额(亿元)
- PLEDGE_DEAL_NUM — 质押笔数(整数)
- REPURCHASE_UNLIMITED_BALANCE / REPURCHASE_LIMITED_BALANCE — 无限售/有限售拆分(亿元)
- PLEDGE_MARKET_CAP — 质押市值(亿元)

extra='allow' 让 INDUSTRY / Y1_CLOSE_ADJCHRATE 等次要字段自动透传,
prompt / 渲染只引用核心 7 字段。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PledgeRecord(BaseModel):
    """单条股权质押周快照。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    trade_date: str = Field(alias="TRADE_DATE")  # 截取 YYYY-MM-DD
    pledge_ratio: Optional[float] = Field(default=None, alias="PLEDGE_RATIO")
    repurchase_balance: Optional[float] = Field(
        default=None, alias="REPURCHASE_BALANCE"
    )
    pledge_deal_num: Optional[int] = Field(default=None, alias="PLEDGE_DEAL_NUM")
    repurchase_unlimited_balance: Optional[float] = Field(
        default=None, alias="REPURCHASE_UNLIMITED_BALANCE"
    )
    repurchase_limited_balance: Optional[float] = Field(
        default=None, alias="REPURCHASE_LIMITED_BALANCE"
    )
    pledge_market_cap: Optional[float] = Field(default=None, alias="PLEDGE_MARKET_CAP")
    source: str = "eastmoney"
