import pytest
from pathlib import Path

from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.basic import StockBasicInfo
from backend.models.financial import IncomeStatement, BalanceSheet
from backend.models.event import DividendRecord
from backend.repositories.market_repo import MarketRepository
from backend.repositories.basic_repo import BasicRepository
from backend.repositories.financial_repo import FinancialRepository
from backend.repositories.event_repo import EventRepository


@pytest.fixture
def market_repo(tmp_path):
    daily_dir = tmp_path / "market" / "A" / "daily"
    adjust_dir = tmp_path / "market" / "A" / "adjust_factor"
    daily_dir.mkdir(parents=True)
    adjust_dir.mkdir(parents=True)
    return MarketRepository(daily_dir, adjust_dir)


@pytest.fixture
def basic_repo(tmp_path):
    basic_dir = tmp_path / "basic" / "A"
    basic_dir.mkdir(parents=True)
    return BasicRepository(basic_dir)


@pytest.fixture
def financial_repo(tmp_path):
    fin_dir = tmp_path / "financial" / "A"
    fin_dir.mkdir(parents=True)
    return FinancialRepository(fin_dir)


@pytest.fixture
def event_repo(tmp_path):
    event_dir = tmp_path / "event" / "A"
    event_dir.mkdir(parents=True)
    return EventRepository(event_dir)


class TestMarketRepository:
    def test_write_and_read_daily_kline(self, market_repo):
        records = [
            DailyKlineRecord(
                date="2026-05-13",
                code="000001.SZ",
                open=10,
                high=11,
                low=9.5,
                close=10.5,
                volume=1000000,
                amount=10000000,
            ),
            DailyKlineRecord(
                date="2026-05-12",
                code="000001.SZ",
                open=9.8,
                high=10.5,
                low=9.6,
                close=10.0,
                volume=900000,
                amount=9000000,
            ),
        ]
        market_repo.write_daily_kline("000001.SZ", records)
        result = market_repo.read_daily_kline("000001.SZ")
        assert len(result) == 2
        assert result[0].date == "2026-05-13"
        assert result[1].date == "2026-05-12"

    def test_read_nonexistent_returns_empty(self, market_repo):
        result = market_repo.read_daily_kline("999999.SZ")
        assert result == []

    def test_append_daily_kline_dedup(self, market_repo):
        records = [
            DailyKlineRecord(
                date="2026-05-12",
                code="000001.SZ",
                open=9.8,
                high=10.5,
                low=9.6,
                close=10.0,
                volume=900000,
                amount=9000000,
            ),
        ]
        market_repo.write_daily_kline("000001.SZ", records)

        new_records = [
            DailyKlineRecord(
                date="2026-05-12",
                code="000001.SZ",
                open=9.8,
                high=10.5,
                low=9.6,
                close=10.0,
                volume=900000,
                amount=9000000,
            ),
            DailyKlineRecord(
                date="2026-05-13",
                code="000001.SZ",
                open=10,
                high=11,
                low=9.5,
                close=10.5,
                volume=1000000,
                amount=10000000,
            ),
        ]
        market_repo.append_daily_kline("000001.SZ", new_records)
        result = market_repo.read_daily_kline("000001.SZ")
        assert len(result) == 2
        assert result[0].date == "2026-05-13"

    def test_write_and_read_adjust_factor(self, market_repo):
        records = [
            AdjustFactorRecord(
                code="000001.SZ", dividOperateDate="2024-06-15", foreAdjustFactor=1.1
            ),
            AdjustFactorRecord(
                code="000001.SZ", dividOperateDate="2025-07-01", foreAdjustFactor=1.2
            ),
        ]
        market_repo.write_adjust_factor("000001.SZ", records)
        result = market_repo.read_adjust_factor("000001.SZ")
        assert len(result) == 2
        assert result[0].dividOperateDate == "2024-06-15"
        assert result[1].dividOperateDate == "2025-07-01"

    def test_list_codes(self, market_repo):
        records = [
            DailyKlineRecord(
                date="2026-05-13",
                code="000001.SZ",
                open=10,
                high=11,
                low=9.5,
                close=10.5,
                volume=1000000,
                amount=10000000,
            ),
        ]
        market_repo.write_daily_kline("000001.SZ", records)
        market_repo.write_daily_kline("600000.SH", records)
        codes = market_repo.list_codes()
        assert set(codes) == {"000001.SZ", "600000.SH"}

    def test_get_latest_date(self, market_repo):
        records = [
            DailyKlineRecord(
                date="2026-05-13",
                code="000001.SZ",
                open=10,
                high=11,
                low=9.5,
                close=10.5,
                volume=1000000,
                amount=10000000,
            ),
            DailyKlineRecord(
                date="2026-05-12",
                code="000001.SZ",
                open=9.8,
                high=10.5,
                low=9.6,
                close=10.0,
                volume=900000,
                amount=9000000,
            ),
        ]
        market_repo.write_daily_kline("000001.SZ", records)
        assert market_repo.get_latest_date("000001.SZ") == "2026-05-13"
        assert market_repo.get_latest_date("999999.SZ") is None


class TestBasicRepository:
    def test_write_and_read_stock_list(self, basic_repo):
        records = [
            StockBasicInfo(
                code="000001.SZ", name="平安银行", ipo_date="1991-04-03", status="1"
            ),
            StockBasicInfo(
                code="600000.SH", name="浦发银行", ipo_date="1999-11-10", status="1"
            ),
        ]
        basic_repo.write_stock_list(records)
        result = basic_repo.read_stock_list()
        assert len(result) == 2
        assert result[0].code == "000001.SZ"

    def test_get_by_code(self, basic_repo):
        records = [
            StockBasicInfo(
                code="000001.SZ", name="平安银行", ipo_date="1991-04-03", status="1"
            ),
            StockBasicInfo(
                code="600000.SH", name="浦发银行", ipo_date="1999-11-10", status="1"
            ),
        ]
        basic_repo.write_stock_list(records)
        found = basic_repo.get_by_code("600000.SH")
        assert found is not None
        assert found.name == "浦发银行"
        assert basic_repo.get_by_code("999999.SZ") is None

    def test_read_empty(self, basic_repo):
        assert basic_repo.read_stock_list() == []


class TestFinancialRepository:
    def test_write_and_read_income(self, financial_repo):
        records = [
            IncomeStatement(REPORT_DATE="2025-12-31", NETPROFIT=80000000),
            IncomeStatement(REPORT_DATE="2025-09-30", NETPROFIT=60000000),
        ]
        financial_repo.write_income("000001.SZ", records)
        result = financial_repo.read_income("000001.SZ")
        assert len(result) == 2
        assert result[0].REPORT_DATE == "2025-12-31"

    def test_append_income_dedup(self, financial_repo):
        records = [IncomeStatement(REPORT_DATE="2025-09-30", NETPROFIT=60000000)]
        financial_repo.write_income("000001.SZ", records)

        new = [
            IncomeStatement(REPORT_DATE="2025-09-30", NETPROFIT=60000000),
            IncomeStatement(REPORT_DATE="2025-12-31", NETPROFIT=80000000),
        ]
        financial_repo.append_income("000001.SZ", new)
        result = financial_repo.read_income("000001.SZ")
        assert len(result) == 2

    def test_write_and_read_balance(self, financial_repo):
        records = [BalanceSheet(REPORT_DATE="2025-12-31", TOTAL_ASSETS=50000000000)]
        financial_repo.write_balance("000001.SZ", records)
        result = financial_repo.read_balance("000001.SZ")
        assert len(result) == 1
        assert result[0].TOTAL_ASSETS == 50000000000

    def test_extra_fields_preserved(self, financial_repo):
        records = [
            IncomeStatement(
                REPORT_DATE="2025-12-31",
                NETPROFIT=80000000,
                SOME_RARE_COLUMN=12345.6,
            )
        ]
        financial_repo.write_income("000001.SZ", records)
        result = financial_repo.read_income("000001.SZ")
        assert result[0].SOME_RARE_COLUMN == 12345.6


class TestEventRepository:
    def test_write_and_read_dividends(self, event_repo):
        records = [
            DividendRecord(
                code="000001.SZ",
                dividOperateDate="2025-07-01",
                dividCashPsBeforeTax=0.3,
            ),
            DividendRecord(
                code="000001.SZ",
                dividOperateDate="2024-06-15",
                dividCashPsBeforeTax=0.25,
            ),
        ]
        event_repo.write_dividends("000001.SZ", records)
        result = event_repo.read_dividends("000001.SZ")
        assert len(result) == 2
        assert result[0].dividOperateDate == "2025-07-01"

    def test_list_codes(self, event_repo):
        records = [
            DividendRecord(code="000001.SZ", dividOperateDate="2025-07-01"),
        ]
        event_repo.write_dividends("000001.SZ", records)
        event_repo.write_dividends("600000.SH", records)
        codes = event_repo.list_codes()
        assert set(codes) == {"000001.SZ", "600000.SH"}

    def test_read_empty(self, event_repo):
        assert event_repo.read_dividends("999999.SZ") == []
