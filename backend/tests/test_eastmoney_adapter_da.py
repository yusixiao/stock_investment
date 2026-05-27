"""§17.8 D&A — EastMoneyAdapter.fetch_da_breakdown 测试。

reportName=RPT_F10_FINANCE_GCASHFLOW,filter 用 SECURITY_CODE + REPORT_DATE
精确定位单期年报 D&A 五项明细。
"""

from __future__ import annotations

from unittest.mock import patch

from backend.adapters.eastmoney_adapter import EastMoneyAdapter


def _resp(payload):
    class R:
        def json(self):
            return payload

    return R()


_ROW = {
    "REPORT_DATE": "2024-12-31 00:00:00",
    "FA_IR_DEPR": 1721165327.14,
    "IA_AMORTIZE": 249170059.35,
    "LPE_AMORTIZE": 20191550.34,
    "USERIGHT_ASSET_AMORTIZE": 94492678.29,
    "DEFER_INCOME_AMORTIZE": None,
}


def test_da_parses_real_fixture():
    payload = {"success": True, "result": {"data": [_ROW]}}
    captured = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        return _resp(payload)

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        out = EastMoneyAdapter().fetch_da_breakdown("600519.SH", "2024-12-31")

    assert out is not None
    assert out["REPORT_DATE"] == "2024-12-31"
    assert out["FA_IR_DEPR"] == 1721165327.14
    assert out["IA_AMORTIZE"] == 249170059.35
    assert out["DEFER_INCOME_AMORTIZE"] is None
    # filter 正确拼装
    assert 'SECURITY_CODE="600519"' in captured["params"]["filter"]
    assert "REPORT_DATE='2024-12-31'" in captured["params"]["filter"]
    assert captured["params"]["reportName"] == "RPT_F10_FINANCE_GCASHFLOW"


def test_da_empty_data_returns_none():
    payload = {"success": True, "result": {"data": []}}
    with patch(
        "backend.adapters.eastmoney_adapter.requests.get",
        lambda *a, **k: _resp(payload),
    ):
        assert EastMoneyAdapter().fetch_da_breakdown("600519.SH", "2030-12-31") is None


def test_da_failed_response_returns_none():
    payload = {"success": False, "result": None, "message": "no data"}
    with patch(
        "backend.adapters.eastmoney_adapter.requests.get",
        lambda *a, **k: _resp(payload),
    ):
        assert EastMoneyAdapter().fetch_da_breakdown("600519.SH", "2024-12-31") is None


def test_da_skips_hk_us():
    """HK / US / 无后缀 直接返 None,不发请求。"""
    called = {"n": 0}

    def fake_get(*a, **k):
        called["n"] += 1
        return _resp({"success": True, "result": {"data": [_ROW]}})

    with patch("backend.adapters.eastmoney_adapter.requests.get", fake_get):
        assert EastMoneyAdapter().fetch_da_breakdown("0700.HK", "2024-12-31") is None
        assert EastMoneyAdapter().fetch_da_breakdown("AAPL.US", "2024-12-31") is None
        assert EastMoneyAdapter().fetch_da_breakdown("AAPL", "2024-12-31") is None
    assert called["n"] == 0


def test_da_network_error_returns_none():
    def boom(*a, **k):
        raise RuntimeError("network down")

    with patch("backend.adapters.eastmoney_adapter.requests.get", boom):
        assert EastMoneyAdapter().fetch_da_breakdown("600519.SH", "2024-12-31") is None
