"""Adapter 层测试 — 全部使用 mock（环境中 API 超时）"""

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from backend.adapters.baostock_adapter import (
    BaoStockAdapter,
    _to_baostock_code,
    _to_standard_code,
)
from backend.adapters.data_source import DataSource, create_default_data_source
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.basic import StockBasicInfo
from backend.models.event import DividendRecord


class TestCodeConversion:
    def test_to_baostock_code(self):
        assert _to_baostock_code("000001.SZ") == "sz.000001"
        assert _to_baostock_code("600000.SH") == "sh.600000"

    def test_to_standard_code(self):
        assert _to_standard_code("sz.000001") == "000001.SZ"
        assert _to_standard_code("sh.600000") == "600000.SH"


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
    def test_fetch_stock_list_merges_industry(self, mock_bs):
        """fetch_stock_list 调 query_stock_basic + query_stock_industry,按 code 合并 industry。

        baostock 的 query_stock_basic 实际不返回 industry 字段,需要单独调
        query_stock_industry 拿到证监会行业分类后 merge。
        """
        mock_bs.login.return_value = MagicMock(error_code="0")
        mock_bs.logout.return_value = None

        # query_stock_basic:不含 industry
        basic_fields = ["code", "code_name", "ipoDate", "outDate", "type", "status"]
        basic_rows = [
            ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
            ["sh.600000", "浦发银行", "1999-11-10", "", "1", "1"],
            [
                "sh.600002",
                "齐鲁石化",
                "1993-08-06",
                "",
                "1",
                "1",
            ],  # 无行业,merge 后应为 None
        ]
        mock_bs.query_stock_basic.return_value = _make_bs_result(
            basic_fields, basic_rows
        )

        # query_stock_industry:独立 API,字段 updateDate/code/code_name/industry/industryClassification
        ind_fields = [
            "updateDate",
            "code",
            "code_name",
            "industry",
            "industryClassification",
        ]
        ind_rows = [
            [
                "2026-05-18",
                "sz.000001",
                "平安银行",
                "J66货币金融服务",
                "证监会行业分类",
            ],
            [
                "2026-05-18",
                "sh.600000",
                "浦发银行",
                "J66货币金融服务",
                "证监会行业分类",
            ],
            # 600002 缺失 — 部分股票确实无行业分类
        ]
        mock_bs.query_stock_industry.return_value = _make_bs_result(
            ind_fields, ind_rows
        )

        adapter = BaoStockAdapter()
        records = adapter.fetch_stock_list()

        assert len(records) == 3
        assert isinstance(records[0], StockBasicInfo)
        assert records[0].code == "000001.SZ"
        assert records[0].name == "平安银行"
        assert records[0].industry == "J66货币金融服务"
        assert records[1].code == "600000.SH"
        assert records[1].industry == "J66货币金融服务"
        # merge 失败的股票:industry 应为 None,不抛
        assert records[2].code == "600002.SH"
        assert records[2].industry is None


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


class TestDataSource:
    def test_create_default_data_source(self):
        with (
            patch("backend.adapters.baostock_adapter.BaoStockAdapter") as mock_bs_cls,
            patch("backend.adapters.eastmoney_adapter.EastMoneyAdapter") as mock_em_cls,
        ):
            ds = create_default_data_source()

        assert isinstance(ds, DataSource)
        assert ds.market is mock_bs_cls.return_value
        assert ds.basic is mock_bs_cls.return_value
        assert ds.event is mock_bs_cls.return_value
        assert ds.financial is mock_em_cls.return_value


class TestBaoStockLoginFailure:
    @patch("backend.adapters.baostock_adapter.bs")
    def test_login_failure_raises(self, mock_bs):
        mock_bs.login.return_value = MagicMock(
            error_code="1", error_msg="network error"
        )

        adapter = BaoStockAdapter()
        with pytest.raises(ConnectionError, match="BaoStock login failed"):
            adapter.fetch_daily_kline("600000.SH", "2026-05-01", "2026-05-12")
