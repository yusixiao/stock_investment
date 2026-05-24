"""§7 控股股东 — EastMoneyAdapter 三个 fetch 方法的 mock 测试。

验证:
1. 调用正确的 reportName + sortColumns=END_DATE
2. 返回值能被 Pydantic 模型解析
3. 空响应/失败优雅降级
"""

from __future__ import annotations

from unittest.mock import patch

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.models.holder import (
    Top10HolderRecord,
    Top10FreeHolderRecord,
    HolderCountRecord,
)


def _fake_response(records: list[dict]) -> dict:
    return {
        "success": True,
        "result": {"data": records, "count": len(records), "pages": 1},
    }


def test_fetch_top10_holders_uses_correct_report_and_sort():
    captured: dict = {}

    def fake_get(url, params, timeout):
        captured["params"] = params

        class R:
            def json(self):
                return _fake_response(
                    [
                        {
                            "SECURITY_CODE": "002594",
                            "END_DATE": "2026-03-31 00:00:00",
                            "HOLDER_RANK": 1,
                            "HOLDER_NAME": "HKSCC",
                            "HOLD_NUM": 3681473217,
                            "HOLD_NUM_RATIO": 40.38,
                        }
                    ]
                )

        return R()

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_top10_holders("002594.SZ")

    assert captured["params"]["reportName"] == "RPT_F10_EH_HOLDERS"
    assert captured["params"]["sortColumns"] == "END_DATE"
    assert len(out) == 1
    assert isinstance(out[0], Top10HolderRecord)
    assert out[0].HOLDER_NAME == "HKSCC"
    # 日期截断到 10 字符(沿用 _clean_record)
    assert out[0].END_DATE == "2026-03-31"


def test_fetch_top10_free_holders_uses_correct_report():
    captured: dict = {}

    def fake_get(url, params, timeout):
        captured["params"] = params

        class R:
            def json(self):
                return _fake_response(
                    [
                        {
                            "SECURITY_CODE": "002594",
                            "END_DATE": "2026-03-31",
                            "HOLDER_RANK": 1,
                            "HOLDER_NAME": "X",
                            "HOLD_NUM": 100,
                            "HOLD_RATIO": 1.0,
                        }
                    ]
                )

        return R()

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_top10_free_holders("002594.SZ")

    assert captured["params"]["reportName"] == "RPT_F10_EH_FREEHOLDERS"
    assert captured["params"]["sortColumns"] == "END_DATE"
    assert len(out) == 1
    assert isinstance(out[0], Top10FreeHolderRecord)


def test_fetch_holder_count_history_uses_correct_report():
    captured: dict = {}

    def fake_get(url, params, timeout):
        captured["params"] = params

        class R:
            def json(self):
                return _fake_response(
                    [
                        {
                            "SECURITY_CODE": "002594",
                            "END_DATE": "2026-03-31 00:00:00",
                            "HOLDER_NUM": 718604,
                            "PRE_END_DATE": "2026-02-28 00:00:00",
                            "PRE_HOLDER_NUM": 732736,
                            "HOLDER_NUM_CHANGE": -14132,
                            "HOLDER_NUM_RATIO": -1.928,
                        }
                    ]
                )

        return R()

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_holder_count_history("002594.SZ")

    assert captured["params"]["reportName"] == "RPT_HOLDERNUMLATEST"
    assert captured["params"]["sortColumns"] == "END_DATE"
    assert len(out) == 1
    assert isinstance(out[0], HolderCountRecord)
    assert out[0].HOLDER_NUM == 718604
    assert out[0].PRE_HOLDER_NUM == 732736


def test_fetch_top10_holders_empty_response():
    def fake_get(url, params, timeout):
        class R:
            def json(self):
                return {"success": False, "message": "no data"}

        return R()

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_top10_holders("999999.SZ")

    assert out == []
