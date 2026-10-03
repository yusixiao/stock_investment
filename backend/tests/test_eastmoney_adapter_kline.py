"""EastMoneyAdapter.fetch_daily_kline — push2his 日K线(yfinance 二源交叉校验用)。

校验点:
- klines 行内字段序 日期,开,收,高,低,量,额(close 在 index 2, high 在 index 3)
- secid 解析:HK 116.{5位} / SH 1.{6位} / SZ·BJ 0.{6位};美股 ValueError
- amount 为真实成交额(区别 yfinance HK amount 恒 0)
- 网络错误经退避重试仍失败返 [](不抛)
全程 mock requests.Session,不发真实网络。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.adapters.eastmoney_adapter import EastMoneyAdapter, _to_kline_secid
from backend.models.market import DailyKlineRecord


_SAMPLE_PAYLOAD = {
    "rc": 0,
    "data": {
        "code": "00700",
        "market": 116,
        "name": "腾讯控股",
        "klines": [
            "2026-06-18,360.000,358.200,363.400,357.000,12345678,4400000000.00",
            "2026-06-19,358.000,365.000,366.000,357.500,23456789,8500000000.00",
        ],
    },
}


def _mock_session(payload):
    """构造一个 session,其 .get(...).json() 返回 payload。返回 (session, get_mock)。"""
    resp = MagicMock()
    resp.json.return_value = payload
    session = MagicMock()
    session.get.return_value = resp
    return session


def test_kline_parses_em_field_order():
    """字段序正确:close=parts[2]、high=parts[3];amount 为真实成交额。"""
    session = _mock_session(_SAMPLE_PAYLOAD)
    with patch(
        "backend.adapters.eastmoney_adapter.requests.Session", return_value=session
    ):
        out = EastMoneyAdapter().fetch_daily_kline(
            "00700.HK", "2026-06-18", "2026-06-19"
        )

    assert len(out) == 2
    assert all(isinstance(r, DailyKlineRecord) for r in out)
    first = out[0]
    assert first.date == "2026-06-18"
    assert first.code == "00700.HK"
    assert first.open == 360.0
    assert first.close == 358.2  # index 2,非 index 1
    assert first.high == 363.4  # index 3
    assert first.low == 357.0
    assert first.volume == 12345678.0
    assert first.amount == 4400000000.0  # 真实成交额,非 0
    # 第二根计算 pctChg = (365-358.2)/358.2*100
    assert out[1].preclose == 358.2
    assert out[1].pctChg == pytest.approx((365.0 - 358.2) / 358.2 * 100)


def test_kline_request_params():
    """secid / fqt / beg / end 正确传入 push2his。"""
    session = _mock_session(_SAMPLE_PAYLOAD)
    with patch(
        "backend.adapters.eastmoney_adapter.requests.Session", return_value=session
    ):
        EastMoneyAdapter().fetch_daily_kline(
            "00700.HK", "2026-01-01", "2026-06-19", fqt=1
        )

    _, kwargs = session.get.call_args
    params = kwargs["params"]
    assert params["secid"] == "116.00700"
    assert params["fqt"] == 1
    assert params["beg"] == "20260101"
    assert params["end"] == "20260619"
    assert params["klt"] == 101


def test_hk_long_history_is_split_into_at_most_one_year_requests():
    """港股历史请求按不超过 12 个月切片，避免 Eastmoney 截断结果。"""
    session = _mock_session(_SAMPLE_PAYLOAD)
    with patch(
        "backend.adapters.eastmoney_adapter.requests.Session", return_value=session
    ):
        EastMoneyAdapter().fetch_daily_kline(
            "00700.HK", "2025-01-01", "2026-06-19"
        )

    assert session.get.call_count == 2
    first_params = session.get.call_args_list[0].kwargs["params"]
    second_params = session.get.call_args_list[1].kwargs["params"]
    assert first_params["beg"] == "20250101"
    assert first_params["end"] == "20251231"
    assert second_params["beg"] == "20260101"
    assert second_params["end"] == "20260619"


def test_kline_secid_resolution():
    assert _to_kline_secid("00700.HK") == "116.00700"
    assert _to_kline_secid("0700.HK") == "116.00700"  # 4位补齐到5位
    assert _to_kline_secid("600519.SH") == "1.600519"
    assert _to_kline_secid("000001.SZ") == "0.000001"
    assert _to_kline_secid("430047.BJ") == "0.430047"
    with pytest.raises(ValueError):
        _to_kline_secid("AAPL.US")  # 美股暂不支持
    with pytest.raises(ValueError):
        _to_kline_secid("AAPL")  # 无市场后缀


def test_kline_empty_klines_returns_empty():
    session = _mock_session({"rc": 0, "data": {"klines": []}})
    with patch(
        "backend.adapters.eastmoney_adapter.requests.Session", return_value=session
    ):
        assert (
            EastMoneyAdapter().fetch_daily_kline("00700.HK", "2026-06-18", "2026-06-19")
            == []
        )


def test_kline_null_data_returns_empty():
    """未收录标的 EM 返回 data=null → []。"""
    session = _mock_session({"rc": 0, "data": None})
    with patch(
        "backend.adapters.eastmoney_adapter.requests.Session", return_value=session
    ):
        assert (
            EastMoneyAdapter().fetch_daily_kline("06806.HK", "2026-06-18", "2026-06-19")
            == []
        )


def test_kline_network_error_returns_empty():
    """session.get 持续抛错 → 退避重试耗尽后返 [],不抛。"""
    session = MagicMock()
    session.get.side_effect = ConnectionError("boom")
    with patch(
        "backend.adapters.eastmoney_adapter.requests.Session", return_value=session
    ), patch("backend.adapters.eastmoney_adapter.time.sleep"):
        out = EastMoneyAdapter().fetch_daily_kline(
            "00700.HK", "2026-06-18", "2026-06-19"
        )
    assert out == []
    # MAX_RETRIES(3)+2 = 5 次尝试
    assert session.get.call_count == 5
