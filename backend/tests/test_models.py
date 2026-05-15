import pytest
from pydantic import ValidationError

from backend.models.market import DailyKlineRecord, AdjustFactorRecord, AggregatedKline
from backend.models.basic import StockBasicInfo
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)
from backend.models.event import DividendRecord


class TestDailyKlineRecord:
    def test_valid_full(self):
        r = DailyKlineRecord(
            date="2026-05-13",
            code="sh.600000",
            open=10.5,
            high=11.0,
            low=10.2,
            close=10.8,
            volume=1000000,
            amount=10800000,
            preclose=10.4,
            turn=1.5,
            tradestatus="1",
            pctChg=3.85,
            peTTM=12.5,
            pbMRQ=1.2,
            psTTM=2.0,
            pcfNcfTTM=8.0,
            isST="0",
        )
        assert r.date == "2026-05-13"
        assert r.close == 10.8
        assert r.isST == "0"

    def test_valid_minimal(self):
        r = DailyKlineRecord(
            date="2026-05-13",
            code="sh.600000",
            open=10.5,
            high=11.0,
            low=10.2,
            close=10.8,
            volume=1000000,
            amount=10800000,
        )
        assert r.preclose is None
        assert r.turn is None
        assert r.peTTM is None

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            DailyKlineRecord(
                date="2026-05-13",
                code="sh.600000",
                open=10.5,
                high=11.0,
                low=10.2,
                volume=1000000,
                amount=10800000,
            )

    def test_type_coercion(self):
        r = DailyKlineRecord(
            date="2026-05-13",
            code="sh.600000",
            open="10.5",
            high="11.0",
            low="10.2",
            close="10.8",
            volume="1000000",
            amount="10800000",
        )
        assert r.open == 10.5
        assert r.volume == 1000000.0


class TestAdjustFactorRecord:
    def test_valid(self):
        r = AdjustFactorRecord(
            code="sh.600000",
            dividOperateDate="2025-06-15",
            foreAdjustFactor=1.234,
            backAdjustFactor=0.81,
        )
        assert r.foreAdjustFactor == 1.234
        assert r.adjustFactor is None

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            AdjustFactorRecord(code="sh.600000", dividOperateDate="2025-06-15")


class TestAggregatedKline:
    def test_valid(self):
        r = AggregatedKline(
            date="2026-05",
            code="sh.600000",
            open=10.0,
            high=12.0,
            low=9.5,
            close=11.5,
            volume=50000000,
            amount=550000000,
        )
        assert r.date == "2026-05"


class TestStockBasicInfo:
    def test_valid(self):
        r = StockBasicInfo(
            code="000001.SZ",
            name="平安银行",
            ipo_date="1991-04-03",
            status="1",
            industry="银行",
        )
        assert r.delist_date is None
        assert r.stock_type is None

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            StockBasicInfo(code="000001.SZ", name="平安银行", ipo_date="1991-04-03")


class TestIncomeStatement:
    def test_valid_with_extra_fields(self):
        r = IncomeStatement(
            REPORT_DATE="2025-12-31",
            OPERATE_INCOME=500000000,
            NETPROFIT=80000000,
            SOME_EXTRA_COLUMN=12345.6,
        )
        assert r.REPORT_DATE == "2025-12-31"
        assert r.OPERATE_INCOME == 500000000
        assert r.SOME_EXTRA_COLUMN == 12345.6

    def test_minimal(self):
        r = IncomeStatement(REPORT_DATE="2025-12-31")
        assert r.NETPROFIT is None
        assert r.BASIC_EPS is None


class TestBalanceSheet:
    def test_valid_with_extra(self):
        r = BalanceSheet(
            REPORT_DATE="2025-12-31",
            TOTAL_ASSETS=10000000000,
            UNKNOWN_COL=999,
        )
        assert r.TOTAL_ASSETS == 10000000000
        assert r.UNKNOWN_COL == 999


class TestCashFlow:
    def test_valid(self):
        r = CashFlow(
            REPORT_DATE="2025-12-31",
            NETCASH_OPERATE=200000000,
        )
        assert r.NETCASH_OPERATE == 200000000
        assert r.CCE_ADD is None


class TestFinancialIndicator:
    def test_valid(self):
        r = FinancialIndicator(
            REPORT_DATE="2025-12-31",
            ROEJQ=15.5,
            XSMLL=30.2,
        )
        assert r.ROEJQ == 15.5
        assert r.ZCFZL is None


class TestDividendRecord:
    def test_valid(self):
        r = DividendRecord(
            code="sh.600000",
            dividOperateDate="2025-06-15",
            dividCashPsBeforeTax=0.5,
            dividStocksPs=0.0,
            dividReserveToStockPs=0.0,
        )
        assert r.dividCashPsBeforeTax == 0.5
        assert r.dividPreNoticeDate is None

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            DividendRecord(code="sh.600000")
