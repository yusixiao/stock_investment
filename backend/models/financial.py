from typing import Optional

from pydantic import BaseModel, ConfigDict


class IncomeStatement(BaseModel):
    """利润表 — A股(中国GAAP) + 港股(IFRS) 统一模型"""

    model_config = ConfigDict(extra="allow")

    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    NOTICE_DATE: Optional[str] = None
    OPERATE_INCOME: Optional[float] = None
    OPERATE_EXPENSE: Optional[float] = None
    OPERATE_PROFIT: Optional[float] = None
    TOTAL_PROFIT: Optional[float] = None
    INCOME_TAX: Optional[float] = None
    NETPROFIT: Optional[float] = None
    PARENT_NETPROFIT: Optional[float] = None
    DEDUCT_PARENT_NETPROFIT: Optional[float] = None
    BASIC_EPS: Optional[float] = None
    # 港股(IFRS)扩展字段
    GROSS_PROFIT: Optional[float] = None
    OTHER_INCOME: Optional[float] = None
    SELLING_EXPENSE: Optional[float] = None
    ADMIN_EXPENSE: Optional[float] = None
    FINANCE_EXPENSE: Optional[float] = None
    SHARE_OF_ASSOCIATES: Optional[float] = None
    INTEREST_INCOME: Optional[float] = None
    # 美股(US-GAAP)扩展字段
    RESEARCH_EXPENSE: Optional[float] = None
    SGA_EXPENSE: Optional[float] = None
    COST_OF_REVENUE: Optional[float] = None
    INTEREST_EXPENSE: Optional[float] = None


class BalanceSheet(BaseModel):
    """资产负债表 — A股(中国GAAP) + 港股(IFRS) 统一模型"""

    model_config = ConfigDict(extra="allow")

    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    TOTAL_ASSETS: Optional[float] = None
    TOTAL_LIABILITIES: Optional[float] = None
    TOTAL_EQUITY: Optional[float] = None
    TOTAL_PARENT_EQUITY: Optional[float] = None
    SHARE_CAPITAL: Optional[float] = None
    CAPITAL_RESERVE: Optional[float] = None
    SURPLUS_RESERVE: Optional[float] = None
    UNASSIGN_RPOFIT: Optional[float] = None
    ACCOUNTS_RECE: Optional[float] = None
    FIXED_ASSET: Optional[float] = None
    INTANGIBLE_ASSET: Optional[float] = None
    GOODWILL: Optional[float] = None
    # 港股(IFRS)扩展字段
    NON_CURRENT_ASSETS: Optional[float] = None
    CURRENT_ASSETS: Optional[float] = None
    CURRENT_LIABILITIES: Optional[float] = None
    NON_CURRENT_LIABILITIES: Optional[float] = None
    NET_CURRENT_ASSETS: Optional[float] = None
    TOTAL_ASSETS_LESS_CL: Optional[float] = None
    MINORITY_EQUITY: Optional[float] = None
    INVENTORY: Optional[float] = None
    CASH_EQUIVALENTS: Optional[float] = None
    SHORT_TERM_DEBT: Optional[float] = None
    LONG_TERM_DEBT: Optional[float] = None
    RETAINED_PROFITS: Optional[float] = None
    TREASURY_SHARES: Optional[float] = None
    # 美股(US-GAAP)扩展字段
    COMMON_STOCK_SHARES: Optional[float] = None


class CashFlow(BaseModel):
    """现金流量表 — A股(中国GAAP) + 港股(IFRS) 统一模型"""

    model_config = ConfigDict(extra="allow")

    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    TOTAL_OPERATE_INFLOW: Optional[float] = None
    TOTAL_OPERATE_OUTFLOW: Optional[float] = None
    NETCASH_OPERATE: Optional[float] = None
    TOTAL_INVEST_INFLOW: Optional[float] = None
    TOTAL_INVEST_OUTFLOW: Optional[float] = None
    NETCASH_INVEST: Optional[float] = None
    TOTAL_FINANCE_INFLOW: Optional[float] = None
    TOTAL_FINANCE_OUTFLOW: Optional[float] = None
    NETCASH_FINANCE: Optional[float] = None
    CCE_ADD: Optional[float] = None
    BEGIN_CCE: Optional[float] = None
    END_CCE: Optional[float] = None
    # 港股(IFRS)扩展字段
    DEPRECIATION_AMORTIZATION: Optional[float] = None
    INTEREST_PAID: Optional[float] = None
    INTEREST_RECEIVED: Optional[float] = None
    DIVIDENDS_PAID: Optional[float] = None
    CAPEX: Optional[float] = None
    TAX_PAID: Optional[float] = None
    CASH_BEFORE_FINANCING: Optional[float] = None
    NEW_BORROWINGS: Optional[float] = None
    REPAY_BORROWINGS: Optional[float] = None
    SHARE_REPURCHASE: Optional[float] = None


class FinancialIndicator(BaseModel):
    """财务指标 — A股 + 港股统一模型"""

    model_config = ConfigDict(extra="allow")

    REPORT_DATE: str
    REPORT_TYPE: Optional[str] = None
    EPSJB: Optional[float] = None
    EPSKCJB: Optional[float] = None
    BPS: Optional[float] = None
    ROEJQ: Optional[float] = None
    ZZCJLL: Optional[float] = None
    XSMLL: Optional[float] = None
    XSJLL: Optional[float] = None
    ZCFZL: Optional[float] = None
    LD: Optional[float] = None
    SD: Optional[float] = None
    ZZCZZTS: Optional[float] = None
    CHZZTS: Optional[float] = None
    YSZKZZTS: Optional[float] = None
    # 港股(IFRS)扩展字段
    DILUTED_EPS: Optional[float] = None
    GROSS_PROFIT_RATIO: Optional[float] = None
    NET_PROFIT_RATIO: Optional[float] = None
    ROA: Optional[float] = None
    ROIC: Optional[float] = None
    OPERATE_INCOME_YOY: Optional[float] = None
    GROSS_PROFIT_YOY: Optional[float] = None
    PARENT_NETPROFIT_YOY: Optional[float] = None
    # 美股(US-GAAP)扩展字段
    REVENUE_YOY: Optional[float] = None
    NETPROFIT_YOY: Optional[float] = None
