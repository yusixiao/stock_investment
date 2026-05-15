from abc import ABC, abstractmethod
from typing import List, Optional

from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.basic import StockBasicInfo
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)
from backend.models.event import DividendRecord


class MarketDataAdapter(ABC):
    """行情数据适配器接口"""

    @abstractmethod
    def fetch_daily_kline(
        self, code: str, start_date: str, end_date: str
    ) -> List[DailyKlineRecord]:
        """获取日K线数据（不复权）"""
        ...

    @abstractmethod
    def fetch_adjust_factor(self, code: str) -> List[AdjustFactorRecord]:
        """获取复权因子"""
        ...


class BasicDataAdapter(ABC):
    """基本信息适配器接口"""

    @abstractmethod
    def fetch_stock_list(self) -> List[StockBasicInfo]:
        """获取全市场股票列表"""
        ...


class FinancialDataAdapter(ABC):
    """财务数据适配器接口"""

    @abstractmethod
    def fetch_income(self, code: str) -> List[IncomeStatement]:
        """获取利润表"""
        ...

    @abstractmethod
    def fetch_balance(self, code: str) -> List[BalanceSheet]:
        """获取资产负债表"""
        ...

    @abstractmethod
    def fetch_cashflow(self, code: str) -> List[CashFlow]:
        """获取现金流量表"""
        ...

    @abstractmethod
    def fetch_indicator(self, code: str) -> List[FinancialIndicator]:
        """获取财务指标"""
        ...


class EventDataAdapter(ABC):
    """事件数据适配器接口"""

    @abstractmethod
    def fetch_dividends(
        self, code: str, year: Optional[str] = None
    ) -> List[DividendRecord]:
        """获取分红/送转记录"""
        ...
