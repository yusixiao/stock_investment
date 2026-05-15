"""EastMoneyAdapter 测试 — 使用 mock"""

from unittest.mock import patch, MagicMock
import pytest

from backend.adapters.eastmoney_adapter import (
    EastMoneyAdapter,
    _fetch_report,
    _clean_record,
)
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)


def _mock_response(data, success=True, pages=1):
    resp = MagicMock()
    resp.json.return_value = {
        "success": success,
        "result": {
            "data": data,
            "pages": pages,
        }
        if success
        else None,
    }
    return resp


class TestCleanRecord:
    def test_removes_none_values(self):
        record = {"REPORT_DATE": "2025-12-31", "VALUE": None, "NUM": 100}
        cleaned = _clean_record(record)
        assert "VALUE" not in cleaned
        assert cleaned["NUM"] == 100

    def test_truncates_datetime_strings(self):
        record = {
            "REPORT_DATE": "2025-12-31 00:00:00",
            "NOTICE_DATE": "2026-03-20 00:00:00",
        }
        cleaned = _clean_record(record)
        assert cleaned["REPORT_DATE"] == "2025-12-31"
        assert cleaned["NOTICE_DATE"] == "2026-03-20"

    def test_keeps_non_date_strings(self):
        record = {"REPORT_TYPE": "年报", "SECURITY_CODE": "000001"}
        cleaned = _clean_record(record)
        assert cleaned["REPORT_TYPE"] == "年报"


class TestFetchReport:
    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_single_page(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"REPORT_DATE": "2025-12-31", "OPERATE_INCOME": 100e6},
                {"REPORT_DATE": "2025-09-30", "OPERATE_INCOME": 75e6},
            ]
        )
        records = _fetch_report("RPT_DMSK_FN_INCOME", "000001.SZ")
        assert len(records) == 2
        mock_get.assert_called_once()

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_multi_page(self, mock_get):
        page1_resp = _mock_response(
            [{"REPORT_DATE": f"2025-{i:02d}-30"} for i in range(1, 13)],
            pages=2,
        )
        page2_resp = _mock_response(
            [{"REPORT_DATE": f"2024-{i:02d}-30"} for i in range(1, 6)],
            pages=2,
        )
        mock_get.side_effect = [page1_resp, page2_resp]
        records = _fetch_report("RPT_DMSK_FN_INCOME", "000001.SZ")
        assert len(records) == 17
        assert mock_get.call_count == 2

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_empty_result(self, mock_get):
        mock_get.return_value = _mock_response([], success=True)
        records = _fetch_report("RPT_DMSK_FN_INCOME", "000001.SZ")
        assert records == []

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_api_failure(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = {"success": False, "result": None}
        mock_get.return_value = resp
        records = _fetch_report("RPT_DMSK_FN_INCOME", "000001.SZ")
        assert records == []

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        records = _fetch_report("RPT_DMSK_FN_INCOME", "000001.SZ")
        assert records == []


class TestEastMoneyAdapterIncome:
    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_income_success(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "REPORT_TYPE_CODE": "年报",
                    "NOTICE_DATE": "2026-03-20 00:00:00",
                    "OPERATE_INCOME": 100000000.0,
                    "OPERATE_EXPENSE": 80000000.0,
                    "OPERATE_PROFIT": 20000000.0,
                    "TOTAL_PROFIT": 18000000.0,
                    "INCOME_TAX": 3000000.0,
                    "PARENT_NETPROFIT": 15000000.0,
                },
            ]
        )
        adapter = EastMoneyAdapter()
        records = adapter.fetch_income("000001.SZ")

        assert len(records) == 1
        r = records[0]
        assert isinstance(r, IncomeStatement)
        assert r.REPORT_DATE == "2025-12-31"
        assert r.OPERATE_INCOME == 100000000.0
        assert r.PARENT_NETPROFIT == 15000000.0

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_income_extra_columns(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "OPERATE_INCOME": 100e6,
                    "SOME_EXTRA_FIELD": 999.0,
                    "SECURITY_CODE": "000001",
                },
            ]
        )
        adapter = EastMoneyAdapter()
        records = adapter.fetch_income("000001.SZ")

        assert len(records) == 1
        assert records[0].model_extra["SOME_EXTRA_FIELD"] == 999.0


class TestEastMoneyAdapterBalance:
    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_balance_success(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "TOTAL_ASSETS": 5000000000.0,
                    "TOTAL_LIABILITIES": 4000000000.0,
                    "TOTAL_EQUITY": 1000000000.0,
                },
            ]
        )
        adapter = EastMoneyAdapter()
        records = adapter.fetch_balance("000001.SZ")

        assert len(records) == 1
        assert isinstance(records[0], BalanceSheet)
        assert records[0].TOTAL_ASSETS == 5000000000.0


class TestEastMoneyAdapterCashflow:
    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_cashflow_success(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "NETCASH_OPERATE": 300000000.0,
                    "NETCASH_INVEST": -200000000.0,
                    "NETCASH_FINANCE": -50000000.0,
                },
            ]
        )
        adapter = EastMoneyAdapter()
        records = adapter.fetch_cashflow("000001.SZ")

        assert len(records) == 1
        assert isinstance(records[0], CashFlow)
        assert records[0].NETCASH_OPERATE == 300000000.0


class TestEastMoneyAdapterIndicator:
    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_indicator_success(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "EPSJB": 1.5,
                    "ROEJQ": 12.5,
                    "XSMLL": 35.0,
                    "ZCFZL": 80.0,
                    "BPS": 10.0,
                },
            ]
        )
        adapter = EastMoneyAdapter()
        records = adapter.fetch_indicator("000001.SZ")

        assert len(records) == 1
        assert isinstance(records[0], FinancialIndicator)
        assert records[0].ROEJQ == 12.5
        assert records[0].BPS == 10.0


class TestEastMoneyAdapterCodeFormat:
    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_code_with_suffix(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"REPORT_DATE": "2025-12-31 00:00:00", "OPERATE_INCOME": 1e6},
            ]
        )
        adapter = EastMoneyAdapter()
        adapter.fetch_income("600000.SH")

        call_params = mock_get.call_args[1]["params"]
        assert '(SECURITY_CODE="600000")' == call_params["filter"]

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_code_without_suffix(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"REPORT_DATE": "2025-12-31 00:00:00", "OPERATE_INCOME": 1e6},
            ]
        )
        adapter = EastMoneyAdapter()
        adapter.fetch_income("000001")

        call_params = mock_get.call_args[1]["params"]
        assert '(SECURITY_CODE="000001")' == call_params["filter"]
