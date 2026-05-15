"""Adapter 层测试 — 全部使用 mock（环境中 API 超时）"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from backend.adapters.baostock_adapter import (
    BaoStockAdapter,
    _to_baostock_code,
    _to_standard_code,
)
from backend.adapters.akshare_adapter import AKShareAdapter, _to_akshare_symbol
from backend.adapters.data_source import DataSource, create_default_data_source
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.basic import StockBasicInfo
from backend.models.event import DividendRecord
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)


class TestCodeConversion:
    def test_to_baostock_code(self):
        assert _to_baostock_code("000001.SZ") == "sz.000001"
        assert _to_baostock_code("600000.SH") == "sh.600000"

    def test_to_standard_code(self):
        assert _to_standard_code("sz.000001") == "000001.SZ"
        assert _to_standard_code("sh.600000") == "600000.SH"

    def test_to_akshare_symbol(self):
        assert _to_akshare_symbol("000001.SZ") == "SZ000001"
        assert _to_akshare_symbol("600000.SH") == "SH600000"


def _make_bs_result(fields, rows):
    """构造 BaoStock 返回值的 mock"""
    rs = MagicMock()
    rs.fields = fields
    rs.error_code = "0"
    call_count = [0]

    def next_fn():
        if call_count[0] < len(rows):
            call_count[0] += 1
            return True
        return False

    def get_row_data():
        return rows[call_count[0] - 1]

    rs.next = next_fn
    rs.get_row_data = get_row_data
    return rs


class TestBaoStockAdapterKline:
    @patch("backend.adapters.baostock_adapter.bs")
    def test_fetch_daily_kline_success(self, mock_bs):
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None

        fields = [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "preclose",
            "volume",
            "amount",
            "adjustflag",
            "turn",
            "tradestatus",
            "pctChg",
            "peTTM",
            "pbMRQ",
            "psTTM",
            "pcfNcfTTM",
            "isST",
        ]
        rows = [
            [
                "2026-05-12",
                "sh.600000",
                "10.5",
                "11.0",
                "10.2",
                "10.8",
                "10.4",
                "1000000",
                "10500000",
                "3",
                "1.5",
                "1",
                "3.85",
                "12.5",
                "1.2",
                "0.8",
                "0.6",
                "0",
            ],
        ]
        mock_bs.query_history_k_data_plus.return_value = _make_bs_result(fields, rows)

        adapter = BaoStockAdapter()
        records = adapter.fetch_daily_kline("600000.SH", "2026-05-01", "2026-05-12")

        assert len(records) == 1
        r = records[0]
        assert isinstance(r, DailyKlineRecord)
        assert r.code == "600000.SH"
        assert r.open == 10.5
        assert r.close == 10.8
        assert r.volume == 1000000
        assert r.isST == "0"

    @patch("backend.adapters.baostock_adapter.bs")
    def test_fetch_daily_kline_empty(self, mock_bs):
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None
        mock_bs.query_history_k_data_plus.return_value = _make_bs_result([], [])

        adapter = BaoStockAdapter()
        records = adapter.fetch_daily_kline("600000.SH", "2026-05-01", "2026-05-12")
        assert records == []

    @patch("backend.adapters.baostock_adapter.bs")
    def test_fetch_daily_kline_missing_optional_fields(self, mock_bs):
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None

        fields = [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "preclose",
            "volume",
            "amount",
            "adjustflag",
            "turn",
            "tradestatus",
            "pctChg",
            "peTTM",
            "pbMRQ",
            "psTTM",
            "pcfNcfTTM",
            "isST",
        ]
        rows = [
            [
                "2026-05-12",
                "sh.600000",
                "10.5",
                "11.0",
                "10.2",
                "10.8",
                "",
                "1000000",
                "10500000",
                "3",
                "",
                "1",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        ]
        mock_bs.query_history_k_data_plus.return_value = _make_bs_result(fields, rows)

        adapter = BaoStockAdapter()
        records = adapter.fetch_daily_kline("600000.SH", "2026-05-01", "2026-05-12")

        assert len(records) == 1
        r = records[0]
        assert r.preclose is None
        assert r.turn is None
        assert r.peTTM is None


class TestBaoStockAdapterAdjustFactor:
    @patch("backend.adapters.baostock_adapter.bs")
    def test_fetch_adjust_factor_success(self, mock_bs):
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None

        fields = [
            "code",
            "dividOperateDate",
            "foreAdjustFactor",
            "backAdjustFactor",
            "adjustFactor",
        ]
        rows = [
            ["sh.600000", "2025-06-15", "1.234", "0.811", "1.5"],
            ["sh.600000", "2024-07-10", "1.100", "0.909", "1.3"],
        ]
        mock_bs.query_adjust_factor.return_value = _make_bs_result(fields, rows)

        adapter = BaoStockAdapter()
        records = adapter.fetch_adjust_factor("600000.SH")

        assert len(records) == 2
        assert isinstance(records[0], AdjustFactorRecord)
        assert records[0].code == "600000.SH"
        assert records[0].foreAdjustFactor == 1.234
        assert records[0].backAdjustFactor == 0.811


class TestBaoStockAdapterStockList:
    @patch("backend.adapters.baostock_adapter.bs")
    def test_fetch_stock_list_success(self, mock_bs):
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None

        fields = [
            "code",
            "code_name",
            "ipoDate",
            "outDate",
            "type",
            "status",
            "industry",
        ]
        rows = [
            ["sz.000001", "平安银行", "1991-04-03", "", "1", "1", "银行"],
            ["sh.600000", "浦发银行", "1999-11-10", "", "1", "1", "银行"],
        ]
        mock_bs.query_stock_basic.return_value = _make_bs_result(fields, rows)

        adapter = BaoStockAdapter()
        records = adapter.fetch_stock_list()

        assert len(records) == 2
        assert isinstance(records[0], StockBasicInfo)
        assert records[0].code == "000001.SZ"
        assert records[0].name == "平安银行"
        assert records[0].industry == "银行"
        assert records[1].code == "600000.SH"


class TestBaoStockAdapterDividends:
    @patch("backend.adapters.baostock_adapter.bs")
    def test_fetch_dividends_success(self, mock_bs):
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None

        fields = [
            "code",
            "dividPreNoticeDate",
            "dividAgmPumDate",
            "dividPlanAnnounceDate",
            "dividPlanDate",
            "dividRegistDate",
            "dividOperateDate",
            "dividPayDate",
            "dividStockMarketDate",
            "dividCashPsBeforeTax",
            "dividCashPsAfterTax",
            "dividStocksPs",
            "dividCashStock",
            "dividReserveToStockPs",
        ]
        rows = [
            [
                "sh.600000",
                "2025-03-01",
                "2025-04-15",
                "2025-05-01",
                "2025-05-10",
                "2025-06-01",
                "2025-06-02",
                "2025-06-10",
                "",
                "0.5",
                "0.45",
                "0",
                "10派5",
                "0",
            ],
        ]
        mock_bs.query_dividend_data.return_value = _make_bs_result(fields, rows)

        adapter = BaoStockAdapter()
        records = adapter.fetch_dividends("600000.SH", year="2025")

        assert len(records) == 1
        assert isinstance(records[0], DividendRecord)
        assert records[0].code == "600000.SH"
        assert records[0].dividOperateDate == "2025-06-02"
        assert records[0].dividCashPsBeforeTax == 0.5


class TestAKShareAdapter:
    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_income_success(self, mock_ak):
        df = pd.DataFrame(
            {
                "REPORT_DATE": ["2025-12-31", "2025-09-30"],
                "REPORT_TYPE": ["年报", "三季报"],
                "NOTICE_DATE": ["2026-03-20", "2025-10-30"],
                "OPERATE_INCOME": [100000000.0, 75000000.0],
                "NETPROFIT": [20000000.0, 15000000.0],
                "PARENT_NETPROFIT": [18000000.0, 13000000.0],
                "BASIC_EPS": [1.5, 1.1],
            }
        )
        mock_ak.stock_profit_sheet_by_report_em.return_value = df

        adapter = AKShareAdapter()
        records = adapter.fetch_income("600000.SH")

        assert len(records) == 2
        assert isinstance(records[0], IncomeStatement)
        assert records[0].REPORT_DATE == "2025-12-31"
        assert records[0].OPERATE_INCOME == 100000000.0
        assert records[0].BASIC_EPS == 1.5

    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_income_empty(self, mock_ak):
        mock_ak.stock_profit_sheet_by_report_em.return_value = pd.DataFrame()

        adapter = AKShareAdapter()
        records = adapter.fetch_income("600000.SH")
        assert records == []

    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_income_exception(self, mock_ak):
        mock_ak.stock_profit_sheet_by_report_em.side_effect = Exception("timeout")

        adapter = AKShareAdapter()
        records = adapter.fetch_income("600000.SH")
        assert records == []

    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_balance_success(self, mock_ak):
        df = pd.DataFrame(
            {
                "REPORT_DATE": ["2025-12-31"],
                "TOTAL_ASSETS": [5000000000.0],
                "TOTAL_LIABILITIES": [4000000000.0],
                "TOTAL_EQUITY": [1000000000.0],
            }
        )
        mock_ak.stock_balance_sheet_by_report_em.return_value = df

        adapter = AKShareAdapter()
        records = adapter.fetch_balance("600000.SH")

        assert len(records) == 1
        assert isinstance(records[0], BalanceSheet)
        assert records[0].TOTAL_ASSETS == 5000000000.0

    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_cashflow_success(self, mock_ak):
        df = pd.DataFrame(
            {
                "REPORT_DATE": ["2025-12-31"],
                "NETCASH_OPERATE": [300000000.0],
                "NETCASH_INVEST": [-200000000.0],
                "NETCASH_FINANCE": [-50000000.0],
            }
        )
        mock_ak.stock_cash_flow_sheet_by_report_em.return_value = df

        adapter = AKShareAdapter()
        records = adapter.fetch_cashflow("600000.SH")

        assert len(records) == 1
        assert isinstance(records[0], CashFlow)
        assert records[0].NETCASH_OPERATE == 300000000.0

    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_indicator_success(self, mock_ak):
        df = pd.DataFrame(
            {
                "REPORT_DATE": ["2025-12-31"],
                "EPSJB": [1.5],
                "ROEJQ": [12.5],
                "XSMLL": [35.0],
                "ZCFZL": [80.0],
            }
        )
        mock_ak.stock_financial_analysis_indicator_em.return_value = df

        adapter = AKShareAdapter()
        records = adapter.fetch_indicator("600000.SH")

        assert len(records) == 1
        assert isinstance(records[0], FinancialIndicator)
        assert records[0].ROEJQ == 12.5

    @patch("backend.adapters.akshare_adapter.ak")
    def test_fetch_income_with_extra_columns(self, mock_ak):
        """验证 extra='allow' 模型可以接收未显式定义的列"""
        df = pd.DataFrame(
            {
                "REPORT_DATE": ["2025-12-31"],
                "OPERATE_INCOME": [100000000.0],
                "SOME_UNKNOWN_COLUMN": [999.0],
                "ANOTHER_COL": ["text_value"],
            }
        )
        mock_ak.stock_profit_sheet_by_report_em.return_value = df

        adapter = AKShareAdapter()
        records = adapter.fetch_income("600000.SH")

        assert len(records) == 1
        assert records[0].REPORT_DATE == "2025-12-31"
        assert records[0].model_extra["SOME_UNKNOWN_COLUMN"] == 999.0
        assert records[0].model_extra["ANOTHER_COL"] == "text_value"


class TestDataSource:
    def test_create_default_data_source(self):
        with (
            patch("backend.adapters.baostock_adapter.BaoStockAdapter") as mock_bs_cls,
            patch("backend.adapters.akshare_adapter.AKShareAdapter") as mock_ak_cls,
        ):
            ds = create_default_data_source()

        assert isinstance(ds, DataSource)
        assert ds.market is mock_bs_cls.return_value
        assert ds.basic is mock_bs_cls.return_value
        assert ds.event is mock_bs_cls.return_value
        assert ds.financial is mock_ak_cls.return_value


class TestBaoStockLoginFailure:
    @patch("backend.adapters.baostock_adapter.bs")
    def test_login_failure_raises(self, mock_bs):
        mock_bs.login.return_value = MagicMock(
            error_code="1", error_msg="network error"
        )

        adapter = BaoStockAdapter()
        with pytest.raises(ConnectionError, match="BaoStock login failed"):
            adapter.fetch_daily_kline("600000.SH", "2026-05-01", "2026-05-12")
