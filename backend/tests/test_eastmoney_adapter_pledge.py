"""§7 股权质押 — EastMoneyAdapter.fetch_pledge_history 测试。

datacenter API 路径(2026-05-26 spike 验证):
- reportName=RPT_CSDC_LIST,A 股全样本,周频快照
- 通过现有 _fetch_report 通道,源 source=HSF10 兼容
"""

from __future__ import annotations

from unittest.mock import patch

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.models.pledge import PledgeRecord


_SAMPLE_RECORDS = [
    {
        "SECURITY_CODE": "600519",
        "TRADE_DATE": "2026-05-22 00:00:00",
        "PLEDGE_RATIO": 0.06,
        "REPURCHASE_BALANCE": 73.66,
        "PLEDGE_DEAL_NUM": 7,
        "REPURCHASE_UNLIMITED_BALANCE": 73.66,
        "REPURCHASE_LIMITED_BALANCE": 0,
        "PLEDGE_MARKET_CAP": 95036.132,
        "INDUSTRY": "白酒",
    },
    {
        "SECURITY_CODE": "600519",
        "TRADE_DATE": "2026-05-15 00:00:00",
        "PLEDGE_RATIO": 0.06,
        "REPURCHASE_BALANCE": 73.66,
        "PLEDGE_DEAL_NUM": 7,
        "REPURCHASE_UNLIMITED_BALANCE": 73.66,
        "REPURCHASE_LIMITED_BALANCE": 0,
        "PLEDGE_MARKET_CAP": 98185.097,
    },
]


def test_pledge_parses_sample_records():
    with patch(
        "backend.adapters.eastmoney_adapter._fetch_report",
        return_value=_SAMPLE_RECORDS,
    ) as mock_fr:
        out = EastMoneyAdapter().fetch_pledge_history("600519.SH")

    mock_fr.assert_called_once_with(
        "RPT_CSDC_LIST", "600519.SH", sort_column="TRADE_DATE"
    )
    assert len(out) == 2
    assert all(isinstance(r, PledgeRecord) for r in out)
    first = out[0]
    # _clean_record 会自动截断 "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DD"
    assert first.trade_date == "2026-05-22"
    assert first.pledge_ratio == 0.06
    assert first.pledge_deal_num == 7
    assert first.repurchase_balance == 73.66
    assert first.pledge_market_cap == 95036.132


def test_pledge_skips_hk_us():
    """HK / US code 直接返空,不发请求。"""
    with patch("backend.adapters.eastmoney_adapter._fetch_report") as mock_fr:
        assert EastMoneyAdapter().fetch_pledge_history("0700.HK") == []
        assert EastMoneyAdapter().fetch_pledge_history("AAPL.US") == []
        assert EastMoneyAdapter().fetch_pledge_history("AAPL") == []
    mock_fr.assert_not_called()


def test_pledge_empty_response_returns_empty():
    with patch(
        "backend.adapters.eastmoney_adapter._fetch_report",
        return_value=[],
    ):
        assert EastMoneyAdapter().fetch_pledge_history("600519.SH") == []


def test_pledge_supports_sh_sz_bj():
    """SH / SZ / BJ 三个交易所都应触发请求。"""
    with patch(
        "backend.adapters.eastmoney_adapter._fetch_report",
        return_value=[],
    ) as mock_fr:
        EastMoneyAdapter().fetch_pledge_history("600519.SH")
        EastMoneyAdapter().fetch_pledge_history("002594.SZ")
        EastMoneyAdapter().fetch_pledge_history("430047.BJ")
    assert mock_fr.call_count == 3
