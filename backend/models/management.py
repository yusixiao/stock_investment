"""§7 管理层 — 高管与持股变动数据模型。

数据源差异(2026-05-26 spike 验证):
- A 股:EastMoney emweb F10 `CompanyManagement/PageAjax`,返 `{gglb, cgbd}`
  - gglb 14 字段(姓名/职位/性别/年龄/学历/任期/简历/...)
  - cgbd 15 字段(增减持,EXECUTIVE_NAME / END_DATE / CHANGE_NUM / TRADE_WAY / ...)
- HK / US:emweb 不支持(返 status=-1),改用 yfinance
  - companyOfficers ~10 条(name / title / age / yearBorn / totalPay / ...)
  - insider_transactions ~30-100 条(Insider / Position / Transaction / Shares / Value / Start Date / ...)

D4 维度真实实现需要的最小字段集(供 LLM 评级使用):
- name(必)、position(必)、age(可)、tenure_text(可,A 股有 INCUMBENT_TIME)、resume(可,A 股有,HK/US 缺)
- 持股变动:date / name / position / change_num / direction(增/减)/ avg_price / trade_way

extra='allow' 让两侧 adapter 把原生字段一起塞进来,prompt 里只引用最小集。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ExecutiveRecord(BaseModel):
    """单个高管记录。统一 schema,A 股填全字段,HK/US 部分字段缺省。

    dedup key 不强制(同名不同职位允许并存)。
    """

    model_config = ConfigDict(extra="allow")

    name: str  # 姓名 / Officer name
    position: Optional[str] = None  # 职位描述(可能逗号分隔多个职位)
    age: Optional[int] = None
    sex: Optional[str] = None  # A 股有,HK/US 缺
    education: Optional[str] = None  # A 股 HIGH_DEGREE,HK/US 缺
    tenure_text: Optional[str] = None  # A 股 INCUMBENT_TIME 如 "2025-11-28至今"
    resume: Optional[str] = None  # A 股 RESUME 长文本,HK/US 缺
    hold_num: Optional[float] = None  # 当前持股数(股)
    salary: Optional[float] = None  # 薪酬(元)
    source: str = "eastmoney"  # eastmoney / yfinance


class ExecutiveHoldChangeRecord(BaseModel):
    """高管持股变动单笔记录。

    direction 由 change_num 符号派生:>0 增持,<0 减持。
    """

    model_config = ConfigDict(extra="allow")

    end_date: str  # YYYY-MM-DD,变动日期
    executive_name: str
    position: Optional[str] = None
    change_num: float  # 变动股数,正=增/负=减
    average_price: Optional[float] = None
    change_after_holdnum: Optional[float] = None
    trade_way: Optional[str] = None  # 二级市场买卖 / 大宗交易 / Open Market Buy / ...
    executive_relation: Optional[str] = (
        None  # 本人 / 配偶 / 子女(A 股)/ Direct Owner(US)
    )
    source: str = "eastmoney"
