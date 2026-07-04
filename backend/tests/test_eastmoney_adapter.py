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
        # 首个明细报表(GBALANCE)非空即命中,并捕获简况所缺的明细科目
        gbalance = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "TOTAL_ASSETS": 5000000000.0,
                    "TOTAL_LIABILITIES": 4000000000.0,
                    "TOTAL_EQUITY": 1000000000.0,
                    "TOTAL_PARENT_EQUITY": 900000000.0,
                    "GOODWILL": 12000000.0,
                    "INTANGIBLE_ASSET": 34000000.0,
                    "MINORITY_EQUITY": 100000000.0,
                },
            ]
        )
        # 明细报表不含行业字段,命中后单独补取简况的 INDUSTRY_NAME/INDUSTRY_CODE
        industry = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "INDUSTRY_NAME": "白酒Ⅱ",
                    "INDUSTRY_CODE": "451700",
                },
            ]
        )
        mock_get.side_effect = [gbalance, industry]
        adapter = EastMoneyAdapter()
        records = adapter.fetch_balance("000001.SZ")

        assert len(records) == 1
        r = records[0]
        assert isinstance(r, BalanceSheet)
        assert r.TOTAL_ASSETS == 5000000000.0
        # 明细科目(简况报表所缺)已捕获
        assert r.TOTAL_PARENT_EQUITY == 900000000.0
        assert r.GOODWILL == 12000000.0
        assert r.INTANGIBLE_ASSET == 34000000.0
        assert r.MINORITY_EQUITY == 100000000.0
        # 行业旁路字段已补回(选股 max_per_sector 依赖)
        assert r.model_extra["INDUSTRY_NAME"] == "白酒Ⅱ"
        assert r.model_extra["INDUSTRY_CODE"] == "451700"
        # 命中明细(1)+ 补取行业(1),共 2 次
        assert mock_get.call_count == 2
        assert (
            mock_get.call_args_list[0].kwargs["params"]["reportName"]
            == "RPT_F10_FINANCE_GBALANCE"
        )
        # 补取用简况、且只拉 1 行
        assert (
            mock_get.call_args_list[1].kwargs["params"]["reportName"]
            == "RPT_DMSK_FN_BALANCE"
        )
        assert mock_get.call_args_list[1].kwargs["params"]["pageSize"] == 1

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_balance_type_fallthrough(self, mock_get):
        # 普通报表(GBALANCE)空 → 落到银行报表(BBALANCE)取数
        empty = _mock_response([], success=True)
        bank = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "TOTAL_PARENT_EQUITY": 4.3e12,
                    "MINORITY_EQUITY": 2.8e10,
                },
            ]
        )
        industry = _mock_response(
            [{"REPORT_DATE": "2025-12-31 00:00:00", "INDUSTRY_NAME": "银行Ⅱ"}]
        )
        mock_get.side_effect = [empty, bank, industry]
        adapter = EastMoneyAdapter()
        records = adapter.fetch_balance("601398.SH")

        assert len(records) == 1
        assert records[0].TOTAL_PARENT_EQUITY == 4.3e12
        assert records[0].model_extra["INDUSTRY_NAME"] == "银行Ⅱ"
        # G 空 → B 命中(2)+ 补取行业(1),共 3 次
        assert mock_get.call_count == 3
        used = [c.kwargs["params"]["reportName"] for c in mock_get.call_args_list]
        assert used == [
            "RPT_F10_FINANCE_GBALANCE",
            "RPT_F10_FINANCE_BBALANCE",
            "RPT_DMSK_FN_BALANCE",
        ]

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_balance_dmsk_fallback(self, mock_get):
        # 4 张明细报表全空 → 兜底回简况 DMSK(保聚合字段,不回归)
        empty = _mock_response([], success=True)
        dmsk = _mock_response(
            [
                {
                    "REPORT_DATE": "2025-12-31 00:00:00",
                    "TOTAL_ASSETS": 8000000.0,
                    "TOTAL_LIABILITIES": 5000000.0,
                    "TOTAL_EQUITY": 3000000.0,
                },
            ]
        )
        mock_get.side_effect = [empty, empty, empty, empty, dmsk]
        adapter = EastMoneyAdapter()
        records = adapter.fetch_balance("999999.SH")

        assert len(records) == 1
        assert records[0].TOTAL_ASSETS == 8000000.0
        assert mock_get.call_count == 5
        used = [c.kwargs["params"]["reportName"] for c in mock_get.call_args_list]
        assert used[-1] == "RPT_DMSK_FN_BALANCE"

    @patch("backend.adapters.eastmoney_adapter.requests.get")
    def test_fetch_balance_industry_fetch_fails_gracefully(self, mock_get):
        # 明细命中但行业补取失败(接口异常/空)→ 仍返回记录,只是无行业字段,不阻断
        gbalance = _mock_response(
            [{"REPORT_DATE": "2025-12-31 00:00:00", "TOTAL_ASSETS": 5e9}]
        )
        industry_fail = _mock_response(None, success=False)
        mock_get.side_effect = [gbalance, industry_fail]
        adapter = EastMoneyAdapter()
        records = adapter.fetch_balance("000001.SZ")

        assert len(records) == 1
        assert records[0].TOTAL_ASSETS == 5e9
        assert "INDUSTRY_NAME" not in (records[0].model_extra or {})
        assert mock_get.call_count == 2


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
