"""Domain 层测试 — 复权计算、周月线聚合、财务时间点、事件子域"""

from unittest.mock import MagicMock, patch
import pytest

from backend.domain.stock import Stock, StockMarket, StockFinancial, StockEvent
from backend.models.market import DailyKlineRecord, AdjustFactorRecord, AggregatedKline
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)
from backend.models.event import DividendRecord


def _make_kline(
    date,
    code="600000.SH",
    open_=10.0,
    high=11.0,
    low=9.5,
    close=10.5,
    volume=1000000,
    amount=10500000,
    tradestatus="1",
    isST="0",
):
    return DailyKlineRecord(
        date=date,
        code=code,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
        tradestatus=tradestatus,
        isST=isST,
    )


def _make_factor(date, fore, code="600000.SH"):
    return AdjustFactorRecord(
        code=code,
        dividOperateDate=date,
        foreAdjustFactor=fore,
    )


class TestStockMarketQfq:
    def test_no_factor_returns_original(self):
        klines = [_make_kline("2026-05-12"), _make_kline("2026-05-11")]
        market = StockMarket("600000.SH", klines, [])
        qfq = market.get_qfq_kline()
        assert len(qfq) == 2
        assert qfq[0].close == 10.5

    def test_single_factor_no_change(self):
        """只有一个复权因子时，ratio = factor/latest = 1.0"""
        klines = [_make_kline("2026-05-12"), _make_kline("2026-05-11")]
        factors = [_make_factor("2026-01-01", 1.5)]
        market = StockMarket("600000.SH", klines, factors)
        qfq = market.get_qfq_kline()
        assert qfq[0].close == 10.5

    def test_qfq_calculation(self):
        """手算验证：两个复权因子
        factor1: 2025-07-01, fore=1.0
        factor2: 2026-01-01, fore=1.2 (latest)
        2025-06-15 的价格应乘以 1.0/1.2 = 0.8333
        2026-03-01 的价格应乘以 1.2/1.2 = 1.0
        """
        klines = [
            _make_kline("2026-03-01", close=12.0, open_=11.0, high=13.0, low=10.0),
            _make_kline("2025-06-15", close=10.0, open_=9.0, high=11.0, low=8.0),
        ]
        factors = [
            _make_factor("2025-07-01", 1.0),
            _make_factor("2026-01-01", 1.2),
        ]
        market = StockMarket("600000.SH", klines, factors)
        qfq = market.get_qfq_kline()

        assert qfq[0].close == 12.0
        assert qfq[1].close == round(10.0 * 1.0 / 1.2, 4)
        assert qfq[1].open == round(9.0 * 1.0 / 1.2, 4)

    def test_qfq_with_multiple_factors(self):
        """三个复权因子，验证区间选择正确"""
        klines = [
            _make_kline("2026-05-01", close=20.0),
            _make_kline("2025-08-01", close=15.0),
            _make_kline("2025-03-01", close=10.0),
        ]
        factors = [
            _make_factor("2025-01-01", 0.8),
            _make_factor("2025-06-01", 1.0),
            _make_factor("2026-01-01", 1.5),
        ]
        market = StockMarket("600000.SH", klines, factors)
        qfq = market.get_qfq_kline()

        # latest_factor = 1.5
        # 2026-05-01: factor=1.5, ratio=1.0 -> close=20.0
        assert qfq[0].close == 20.0
        # 2025-08-01: factor=1.0, ratio=1.0/1.5 -> close=15*0.6667=10.0
        assert qfq[1].close == round(15.0 * 1.0 / 1.5, 4)
        # 2025-03-01: factor=0.8, ratio=0.8/1.5 -> close=10*0.5333=5.3333
        assert qfq[2].close == round(10.0 * 0.8 / 1.5, 4)


class TestStockMarketAggregation:
    def _make_daily_data(self):
        """构造2周的日线数据（10天）"""
        dates = [
            "2026-05-12",
            "2026-05-11",
            "2026-05-09",
            "2026-05-08",
            "2026-05-07",
            "2026-05-06",
            "2026-05-05",
            "2026-05-02",
            "2026-04-30",
            "2026-04-29",
        ]
        klines = []
        for i, d in enumerate(dates):
            klines.append(
                _make_kline(
                    d,
                    close=10.0 + i * 0.5,
                    open_=10.0 + i * 0.3,
                    high=12.0 + i * 0.2,
                    low=9.0 + i * 0.1,
                    volume=1000000 + i * 100000,
                    amount=10000000 + i * 1000000,
                )
            )
        return klines

    def test_weekly_aggregation(self):
        klines = self._make_daily_data()
        market = StockMarket("600000.SH", klines, [])
        weekly = market.get_weekly_kline()

        assert len(weekly) > 0
        assert all(isinstance(w, AggregatedKline) for w in weekly)
        assert weekly[0].date >= weekly[-1].date

    def test_monthly_aggregation(self):
        klines = self._make_daily_data()
        market = StockMarket("600000.SH", klines, [])
        monthly = market.get_monthly_kline()

        assert len(monthly) > 0
        for m in monthly:
            assert m.code == "600000.SH"

    def test_empty_kline(self):
        market = StockMarket("600000.SH", [], [])
        assert market.get_weekly_kline() == []
        assert market.get_monthly_kline() == []


class TestStockMarketQueries:
    def test_get_close_on(self):
        klines = [
            _make_kline("2026-05-12", close=10.5),
            _make_kline("2026-05-11", close=10.2),
        ]
        market = StockMarket("600000.SH", klines, [])
        assert market.get_close_on("2026-05-12") == 10.5
        assert market.get_close_on("2026-05-11") == 10.2
        assert market.get_close_on("2026-05-10") is None

    def test_get_kline_range(self):
        klines = [
            _make_kline("2026-05-12"),
            _make_kline("2026-05-11"),
            _make_kline("2026-05-09"),
            _make_kline("2026-05-08"),
        ]
        market = StockMarket("600000.SH", klines, [])
        result = market.get_kline_range("2026-05-09", "2026-05-11")
        assert len(result) == 2
        assert result[0].date == "2026-05-11"
        assert result[1].date == "2026-05-09"

    def test_is_trade_day(self):
        klines = [_make_kline("2026-05-12")]
        market = StockMarket("600000.SH", klines, [])
        assert market.is_trade_day("2026-05-12") is True
        assert market.is_trade_day("2026-05-13") is False

    def test_is_suspended(self):
        klines = [_make_kline("2026-05-12", tradestatus="0")]
        market = StockMarket("600000.SH", klines, [])
        assert market.is_suspended("2026-05-12") is True

    def test_is_st(self):
        klines = [_make_kline("2026-05-12", isST="1")]
        market = StockMarket("600000.SH", klines, [])
        assert market.is_st("2026-05-12") is True

    def test_get_qfq_close_on(self):
        klines = [
            _make_kline("2026-05-12", close=12.0),
            _make_kline("2025-06-15", close=10.0),
        ]
        factors = [
            _make_factor("2025-07-01", 1.0),
            _make_factor("2026-01-01", 1.2),
        ]
        market = StockMarket("600000.SH", klines, factors)
        assert market.get_qfq_close_on("2026-05-12") == 12.0
        assert market.get_qfq_close_on("2025-06-15") == round(10.0 * 1.0 / 1.2, 4)
        assert market.get_qfq_close_on("2020-01-01") is None


class TestStockFinancial:
    def _make_financial(self):
        income = [
            IncomeStatement(
                REPORT_DATE="2025-12-31",
                REPORT_TYPE="年报",
                NOTICE_DATE="2026-03-20",
                OPERATE_INCOME=100e6,
                PARENT_NETPROFIT=20e6,
            ),
            IncomeStatement(
                REPORT_DATE="2025-09-30",
                REPORT_TYPE="三季报",
                NOTICE_DATE="2025-10-30",
                OPERATE_INCOME=75e6,
                PARENT_NETPROFIT=15e6,
            ),
            IncomeStatement(
                REPORT_DATE="2025-06-30",
                REPORT_TYPE="中报",
                NOTICE_DATE="2025-08-28",
                OPERATE_INCOME=50e6,
                PARENT_NETPROFIT=10e6,
            ),
            IncomeStatement(
                REPORT_DATE="2024-12-31",
                REPORT_TYPE="年报",
                NOTICE_DATE="2025-03-25",
                OPERATE_INCOME=80e6,
                PARENT_NETPROFIT=16e6,
            ),
        ]
        indicator = [
            FinancialIndicator(REPORT_DATE="2025-12-31", ROEJQ=15.0),
            FinancialIndicator(REPORT_DATE="2025-09-30", ROEJQ=12.0),
            FinancialIndicator(REPORT_DATE="2025-06-30", ROEJQ=10.0),
        ]
        return StockFinancial("600000.SH", income, [], [], indicator)

    def test_get_latest_report(self):
        fin = self._make_financial()
        latest = fin.get_latest_report()
        assert latest.REPORT_DATE == "2025-12-31"

    def test_get_latest_report_by_type(self):
        fin = self._make_financial()
        latest = fin.get_latest_report(report_type="三季报")
        assert latest.REPORT_DATE == "2025-09-30"

    def test_get_report_on_avoids_future_data(self):
        """2025-11-01时，年报尚未公告，应返回三季报"""
        fin = self._make_financial()
        report = fin.get_report_on("2025-11-01")
        assert report.REPORT_DATE == "2025-09-30"

    def test_get_report_on_after_announcement(self):
        """2026-03-25后，年报已公告"""
        fin = self._make_financial()
        report = fin.get_report_on("2026-04-01")
        assert report.REPORT_DATE == "2025-12-31"

    def test_get_report_on_no_available(self):
        fin = self._make_financial()
        report = fin.get_report_on("2024-01-01")
        assert report is None

    def test_get_roe_history(self):
        fin = self._make_financial()
        roe = fin.get_roe_history(n=3)
        assert roe == [15.0, 12.0, 10.0]

    def test_get_revenue_growth(self):
        fin = self._make_financial()
        growth = fin.get_revenue_growth(n=3)
        assert len(growth) == 3
        assert growth[0] == round((100e6 - 75e6) / 75e6, 4)

    def test_get_net_profit_history(self):
        fin = self._make_financial()
        profits = fin.get_net_profit_history(n=4)
        assert profits == [20e6, 15e6, 10e6, 16e6]


class TestStockEvent:
    def _make_events(self):
        divs = [
            DividendRecord(
                code="600000.SH",
                dividOperateDate="2025-06-15",
                dividCashPsBeforeTax=0.5,
                dividStocksPs=0.0,
            ),
            DividendRecord(
                code="600000.SH",
                dividOperateDate="2025-11-20",
                dividCashPsBeforeTax=0.3,
                dividStocksPs=0.0,
            ),
            DividendRecord(
                code="600000.SH",
                dividOperateDate="2024-06-10",
                dividCashPsBeforeTax=0.4,
                dividStocksPs=0.0,
            ),
        ]
        return StockEvent("600000.SH", divs)

    def test_get_dividend_on(self):
        ev = self._make_events()
        d = ev.get_dividend_on("2025-06-15")
        assert d is not None
        assert d.dividCashPsBeforeTax == 0.5

    def test_get_dividend_on_not_found(self):
        ev = self._make_events()
        assert ev.get_dividend_on("2025-01-01") is None

    def test_get_dividends_in_range(self):
        ev = self._make_events()
        result = ev.get_dividends_in_range("2025-01-01", "2025-12-31")
        assert len(result) == 2

    def test_get_annual_dividend_yield(self):
        ev = self._make_events()
        # 2025年总派息 = 0.5 + 0.3 = 0.8, 股价10.0
        yield_val = ev.get_annual_dividend_yield(2025, 10.0)
        assert yield_val == 0.08

    def test_get_annual_dividend_yield_zero_price(self):
        ev = self._make_events()
        assert ev.get_annual_dividend_yield(2025, 0.0) == 0.0


class TestStockAggregate:
    def test_load_market(self):
        mock_market_repo = MagicMock()
        mock_market_repo.read_daily_kline.return_value = [_make_kline("2026-05-12")]
        mock_market_repo.read_adjust_factor.return_value = []

        stock = Stock("600000.SH", market_repo=mock_market_repo)
        stock.load_market()

        assert stock.market is not None
        assert stock.market.code == "600000.SH"
        assert len(stock.market.daily_kline) == 1
        mock_market_repo.read_daily_kline.assert_called_once_with("600000.SH")

    def test_load_financial(self):
        mock_fin_repo = MagicMock()
        mock_fin_repo.read_income.return_value = [
            IncomeStatement(REPORT_DATE="2025-12-31")
        ]
        mock_fin_repo.read_balance.return_value = []
        mock_fin_repo.read_cashflow.return_value = []
        mock_fin_repo.read_indicator.return_value = []

        stock = Stock("600000.SH", financial_repo=mock_fin_repo)
        stock.load_financial()

        assert stock.financial is not None
        assert len(stock.financial.income) == 1

    def test_load_event(self):
        mock_event_repo = MagicMock()
        mock_event_repo.read_dividends.return_value = [
            DividendRecord(code="600000.SH", dividOperateDate="2025-06-15")
        ]

        stock = Stock("600000.SH", event_repo=mock_event_repo)
        stock.load_event()

        assert stock.event is not None
        assert len(stock.event.dividends) == 1

    def test_load_all(self):
        mock_market = MagicMock()
        mock_market.read_daily_kline.return_value = []
        mock_market.read_adjust_factor.return_value = []

        mock_fin = MagicMock()
        mock_fin.read_income.return_value = []
        mock_fin.read_balance.return_value = []
        mock_fin.read_cashflow.return_value = []
        mock_fin.read_indicator.return_value = []

        mock_event = MagicMock()
        mock_event.read_dividends.return_value = []

        mock_basic = MagicMock()
        mock_basic.read_stock_list.return_value = []

        stock = Stock(
            "600000.SH",
            market_repo=mock_market,
            financial_repo=mock_fin,
            event_repo=mock_event,
            basic_repo=mock_basic,
        )
        stock.load_all()

        assert stock.market is not None
        assert stock.financial is not None
        assert stock.event is not None
