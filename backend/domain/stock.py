from typing import List, Optional

import pandas as pd

from backend.models.market import DailyKlineRecord, AdjustFactorRecord, AggregatedKline
from backend.models.basic import StockBasicInfo
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)
from backend.models.event import DividendRecord
from backend.repositories import (
    MarketRepository,
    BasicRepository,
    FinancialRepository,
    EventRepository,
)


class StockMarket:
    """行情子域 — 回测引擎主要消费者"""

    def __init__(
        self,
        code: str,
        daily_kline: List[DailyKlineRecord],
        adjust_factor: List[AdjustFactorRecord],
    ):
        self.code = code
        self.daily_kline = daily_kline
        self.adjust_factor = adjust_factor
        self._date_index: dict = {}
        for i, rec in enumerate(daily_kline):
            self._date_index[rec.date] = i

    def get_qfq_kline(self) -> List[DailyKlineRecord]:
        """动态计算前复权K线: qfq_price = raw_price × (factor / latest_factor)"""
        if not self.adjust_factor or not self.daily_kline:
            return list(self.daily_kline)

        sorted_factors = sorted(self.adjust_factor, key=lambda x: x.dividOperateDate)
        latest_factor = sorted_factors[-1].foreAdjustFactor

        factor_map = {}
        for f in sorted_factors:
            factor_map[f.dividOperateDate] = f.foreAdjustFactor

        dates_sorted = sorted(factor_map.keys())

        def _get_factor_for_date(date: str) -> float:
            result = sorted_factors[0].foreAdjustFactor
            for d in dates_sorted:
                if d <= date:
                    result = factor_map[d]
                else:
                    break
            return result

        records = []
        for rec in self.daily_kline:
            factor = _get_factor_for_date(rec.date)
            ratio = factor / latest_factor
            records.append(
                DailyKlineRecord(
                    date=rec.date,
                    code=rec.code,
                    open=round(rec.open * ratio, 4),
                    high=round(rec.high * ratio, 4),
                    low=round(rec.low * ratio, 4),
                    close=round(rec.close * ratio, 4),
                    preclose=round(rec.preclose * ratio, 4) if rec.preclose else None,
                    volume=rec.volume,
                    amount=rec.amount,
                    adjustflag=rec.adjustflag,
                    turn=rec.turn,
                    tradestatus=rec.tradestatus,
                    pctChg=rec.pctChg,
                    peTTM=rec.peTTM,
                    pbMRQ=rec.pbMRQ,
                    psTTM=rec.psTTM,
                    pcfNcfTTM=rec.pcfNcfTTM,
                    isST=rec.isST,
                )
            )
        return records

    def get_weekly_kline(self) -> List[AggregatedKline]:
        """从日线聚合周线"""
        return self._aggregate("weekly")

    def get_monthly_kline(self) -> List[AggregatedKline]:
        """从日线聚合月线"""
        return self._aggregate("monthly")

    def _aggregate(self, period: str) -> List[AggregatedKline]:
        if not self.daily_kline:
            return []

        df = pd.DataFrame([r.model_dump() for r in self.daily_kline])
        asc = df.sort_values("date").reset_index(drop=True)
        asc["date_dt"] = pd.to_datetime(asc["date"])

        if period == "weekly":
            asc["period_key"] = asc["date_dt"].dt.to_period("W-FRI")
        else:
            asc["period_key"] = asc["date_dt"].dt.to_period("M")

        grouped = asc.groupby("period_key", sort=True)
        result = pd.DataFrame(
            {
                "date": grouped["date"].last(),
                "open": grouped["open"].first(),
                "high": grouped["high"].max(),
                "low": grouped["low"].min(),
                "close": grouped["close"].last(),
                "volume": grouped["volume"].sum(),
                "amount": grouped["amount"].sum(),
            }
        ).reset_index(drop=True)

        result = result.sort_values("date", ascending=False).reset_index(drop=True)

        records = []
        for _, row in result.iterrows():
            records.append(
                AggregatedKline(
                    date=row["date"],
                    code=self.code,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    amount=row["amount"],
                )
            )
        return records

    def get_close_on(self, date: str) -> Optional[float]:
        """获取指定日期收盘价"""
        idx = self._date_index.get(date)
        if idx is not None:
            return self.daily_kline[idx].close
        return None

    def get_qfq_close_on(self, date: str) -> Optional[float]:
        """获取指定日期前复权收盘价"""
        idx = self._date_index.get(date)
        if idx is None:
            return None

        rec = self.daily_kline[idx]
        if not self.adjust_factor:
            return rec.close

        sorted_factors = sorted(self.adjust_factor, key=lambda x: x.dividOperateDate)
        latest_factor = sorted_factors[-1].foreAdjustFactor

        factor_map = {f.dividOperateDate: f.foreAdjustFactor for f in sorted_factors}
        dates_sorted = sorted(factor_map.keys())

        current_factor = sorted_factors[0].foreAdjustFactor
        for d in dates_sorted:
            if d <= date:
                current_factor = factor_map[d]
            else:
                break

        return round(rec.close * current_factor / latest_factor, 4)

    def get_kline_range(self, start: str, end: str) -> List[DailyKlineRecord]:
        """获取日期范围内的K线"""
        return [r for r in self.daily_kline if start <= r.date <= end]

    def is_trade_day(self, date: str) -> bool:
        """判断是否交易日"""
        return date in self._date_index

    def is_suspended(self, date: str) -> bool:
        """判断是否停牌（tradestatus='0'表示停牌）"""
        idx = self._date_index.get(date)
        if idx is None:
            return False
        return self.daily_kline[idx].tradestatus == "0"

    def is_st(self, date: str) -> bool:
        """判断是否ST"""
        idx = self._date_index.get(date)
        if idx is None:
            return False
        return self.daily_kline[idx].isST == "1"


class StockFinancial:
    """财务子域 — 基本面策略主要消费者"""

    def __init__(
        self,
        code: str,
        income: List[IncomeStatement],
        balance: List[BalanceSheet],
        cashflow: List[CashFlow],
        indicator: List[FinancialIndicator],
    ):
        self.code = code
        self.income = income
        self.balance = balance
        self.cashflow = cashflow
        self.indicator = indicator

    def get_latest_report(
        self, report_type: Optional[str] = None
    ) -> Optional[IncomeStatement]:
        """获取最新报告（按 REPORT_DATE 倒序第一条）"""
        filtered = self.income
        if report_type:
            filtered = [r for r in filtered if r.REPORT_TYPE == report_type]
        if not filtered:
            return None
        return sorted(filtered, key=lambda x: x.REPORT_DATE, reverse=True)[0]

    def get_report_on(self, date: str) -> Optional[IncomeStatement]:
        """获取指定日期可用的最新报告（按公告日期，避免未来数据）"""
        available = [r for r in self.income if r.NOTICE_DATE and r.NOTICE_DATE <= date]
        if not available:
            return None
        return sorted(available, key=lambda x: x.REPORT_DATE, reverse=True)[0]

    def get_roe_history(self, n: int = 20) -> List[float]:
        """获取历史ROE序列（从新到旧）"""
        sorted_ind = sorted(self.indicator, key=lambda x: x.REPORT_DATE, reverse=True)
        result = []
        for ind in sorted_ind[:n]:
            if ind.ROEJQ is not None:
                result.append(ind.ROEJQ)
        return result

    def get_revenue_growth(self, n: int = 4) -> List[float]:
        """获取营收增长率序列（需至少n+1期数据计算同比）"""
        sorted_income = sorted(self.income, key=lambda x: x.REPORT_DATE, reverse=True)
        if len(sorted_income) < 2:
            return []

        result = []
        for i in range(min(n, len(sorted_income) - 1)):
            curr = sorted_income[i]
            prev = sorted_income[i + 1]
            if curr.OPERATE_INCOME and prev.OPERATE_INCOME and prev.OPERATE_INCOME != 0:
                growth = (curr.OPERATE_INCOME - prev.OPERATE_INCOME) / abs(
                    prev.OPERATE_INCOME
                )
                result.append(round(growth, 4))
        return result

    def get_net_profit_history(self, n: int = 20) -> List[float]:
        """获取净利润历史（从新到旧）"""
        sorted_income = sorted(self.income, key=lambda x: x.REPORT_DATE, reverse=True)
        result = []
        for inc in sorted_income[:n]:
            if inc.PARENT_NETPROFIT is not None:
                result.append(inc.PARENT_NETPROFIT)
        return result


class StockEvent:
    """事件子域 — 分红送转"""

    def __init__(self, code: str, dividends: List[DividendRecord]):
        self.code = code
        self.dividends = dividends

    def get_dividend_on(self, date: str) -> Optional[DividendRecord]:
        """获取指定日期的分红事件（除权除息日匹配）"""
        for d in self.dividends:
            if d.dividOperateDate == date:
                return d
        return None

    def get_dividends_in_range(self, start: str, end: str) -> List[DividendRecord]:
        """获取日期范围内的所有分红事件"""
        return [d for d in self.dividends if start <= d.dividOperateDate <= end]

    def get_annual_dividend_yield(self, year: int, close_price: float) -> float:
        """计算指定年度股息率 = 年度每股税前派息合计 / 收盘价"""
        if close_price <= 0:
            return 0.0
        year_str = str(year)
        total_cash = 0.0
        for d in self.dividends:
            if d.dividOperateDate.startswith(year_str) and d.dividCashPsBeforeTax:
                total_cash += d.dividCashPsBeforeTax
        return round(total_cash / close_price, 4)


class Stock:
    """股票聚合根 — 统一入口，子域按需加载"""

    def __init__(
        self,
        code: str,
        market_repo: Optional["MarketRepository"] = None,
        financial_repo: Optional["FinancialRepository"] = None,
        event_repo: Optional["EventRepository"] = None,
        basic_repo: Optional["BasicRepository"] = None,
    ):
        self.code = code
        self._market_repo = market_repo
        self._financial_repo = financial_repo
        self._event_repo = event_repo
        self._basic_repo = basic_repo

        self.basic: Optional[StockBasicInfo] = None
        self.market: Optional[StockMarket] = None
        self.financial: Optional[StockFinancial] = None
        self.event: Optional[StockEvent] = None

    def load_basic(self) -> None:
        """加载基本信息"""
        if not self._basic_repo:
            raise RuntimeError("basic_repo not provided")
        all_stocks = self._basic_repo.read_stock_list()
        for s in all_stocks:
            if s.code == self.code:
                self.basic = s
                return

    def load_market(self) -> None:
        """加载行情数据"""
        if not self._market_repo:
            raise RuntimeError("market_repo not provided")
        daily = self._market_repo.read_daily_kline(self.code)
        factor = self._market_repo.read_adjust_factor(self.code)
        self.market = StockMarket(self.code, daily, factor)

    def load_financial(self) -> None:
        """加载财务数据"""
        if not self._financial_repo:
            raise RuntimeError("financial_repo not provided")
        income = self._financial_repo.read_income(self.code)
        balance = self._financial_repo.read_balance(self.code)
        cashflow = self._financial_repo.read_cashflow(self.code)
        indicator = self._financial_repo.read_indicator(self.code)
        self.financial = StockFinancial(self.code, income, balance, cashflow, indicator)

    def load_event(self) -> None:
        """加载事件数据"""
        if not self._event_repo:
            raise RuntimeError("event_repo not provided")
        dividends = self._event_repo.read_dividends(self.code)
        self.event = StockEvent(self.code, dividends)

    def load_all(self) -> None:
        """加载所有子域"""
        if self._basic_repo:
            self.load_basic()
        if self._market_repo:
            self.load_market()
        if self._financial_repo:
            self.load_financial()
        if self._event_repo:
            self.load_event()
