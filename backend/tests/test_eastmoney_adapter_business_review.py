"""EastMoneyAdapter.fetch_business_review — D5 经营评述数据源 mock 测试。

数据源:RPT_F10_OP_BUSINESSANALYSIS(2026-05-26 spike 验证 603939 实测)。
"""

from __future__ import annotations

from unittest.mock import patch

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.models.business_review import BusinessReviewRecord


def _fake_response(records: list[dict]) -> dict:
    return {
        "success": True,
        "result": {"data": records, "count": len(records), "pages": 1},
    }


def test_fetch_business_review_uses_correct_report_name():
    captured: dict = {}

    def fake_get(url, params, timeout):
        captured["params"] = params

        class R:
            def json(self):
                return _fake_response(
                    [
                        {
                            "SECURITY_CODE": "603939",
                            "REPORT_DATE": "2025-12-31 00:00:00",
                            "REPORT_NAME": "2025年报",
                            "BUSINESS_REVIEW": "（一）主要业务概述...全文 1400 字省略",
                            "SECURITY_NAME_ABBR": "益丰药房",
                        },
                        {
                            "SECURITY_CODE": "603939",
                            "REPORT_DATE": "2024-12-31 00:00:00",
                            "REPORT_NAME": "2024年报",
                            "BUSINESS_REVIEW": "2024 年报全文",
                        },
                    ]
                )

        return R()

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_business_review("603939.SH")

    assert captured["params"]["reportName"] == "RPT_F10_OP_BUSINESSANALYSIS"
    assert captured["params"]["sortColumns"] == "REPORT_DATE"
    assert len(out) == 2
    assert isinstance(out[0], BusinessReviewRecord)
    assert out[0].REPORT_NAME == "2025年报"
    assert out[0].REPORT_DATE == "2025-12-31"  # _clean_record 截到 10 字符
    assert "主要业务概述" in (out[0].BUSINESS_REVIEW or "")


def test_fetch_business_review_empty_response():
    def fake_get(url, params, timeout):
        class R:
            def json(self):
                return {"success": True, "result": {"data": [], "pages": 0}}

        return R()

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_business_review("000000.SZ")

    assert out == []


def test_fetch_business_review_request_failure_returns_empty():
    """网络全失败时,_fetch_page_with_retry 重试耗尽返回 None,适配器返回空列表。"""

    def fake_get(url, params, timeout):
        raise ConnectionError("network down")

    with (
        patch("backend.adapters.eastmoney_adapter.requests.get", fake_get),
        patch("backend.adapters.eastmoney_adapter.time.sleep", lambda _s: None),
    ):
        out = EastMoneyAdapter().fetch_business_review("603939.SH")

    assert out == []
