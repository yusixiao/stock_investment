"""问股期 1 — Task 22:§4 资产负债表测试。"""

from unittest.mock import MagicMock

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s04_balance
from services.agent.core.symbol import StockRef


def test_section_4_basic():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "TOTAL_ASSETS": 8.0e11,
            "TOTAL_LIABILITIES": 5.5e11,
            "TOTAL_EQUITY": 2.5e11,
            "TOTAL_CURRENT_ASSETS": 3.0e11,
            "TOTAL_CURRENT_LIAB": 3.0e11,
            "MONETARY_FUND": 6.0e10,
            "INVENTORIES": 4.0e10,
            "FIXED_ASSETS": 1.5e11,
            "INTANGIBLE_ASSETS": 2.0e10,
            "GOODWILL": 5.0e9,
            "BPS": 85.5,
        }
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s04_balance.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §4 资产负债表" in out
    assert "总资产" in out and "总负债" in out and "股东权益" in out
    assert "800,000" in out  # 8e11/1e6
    assert "85.50" in out  # BPS


def test_section_4_empty_emits_warning():
    s = MagicMock()
    s.query_financial_for_section.return_value = []
    out = s04_balance.build(
        StockRef("X", "x", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out


# ---- §4P 母公司资产负债表(Task 23) ----

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s04p_parent_balance  # noqa: E402


def test_s04p_returns_none_for_hk():
    ref = StockRef("00700.HK", "腾讯", "HK")
    assert (
        s04p_parent_balance.build(
            ref, store=MagicMock(), stock_index=MagicMock(), indicators=MagicMock()
        )
        is None
    )


def test_s04p_returns_none_for_us():
    ref = StockRef("AAPL", "Apple", "US")
    assert (
        s04p_parent_balance.build(
            ref, store=MagicMock(), stock_index=MagicMock(), indicators=MagicMock()
        )
        is None
    )


def test_s04p_a_share_returns_table():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "TOTAL_ASSETS": 3.5e11,
            "TOTAL_LIABILITIES": 2.4e11,
            "TOTAL_EQUITY": 1.1e11,
            "MONETARY_FUND": 4.0e10,
            "LONG_EQUITY_INVEST": 8.0e10,
        },
        {
            "REPORT_DATE": "2024-12-31",
            "TOTAL_ASSETS": 3.0e11,
            "TOTAL_LIABILITIES": 2.1e11,
            "TOTAL_EQUITY": 9.0e10,
            "MONETARY_FUND": 3.5e10,
            "LONG_EQUITY_INVEST": 7.0e10,
        },
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s04p_parent_balance.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert out is not None
    assert "§4P 母公司资产负债表" in out
    assert "总资产" in out and "总负债" in out and "股东权益" in out
    assert "对子公司长投" in out


def test_s04p_a_share_no_parent_data_returns_warning():
    s = MagicMock()
    s.query_financial_for_section.return_value = []
    out = s04p_parent_balance.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert out is not None
    assert "母公司数据缺失" in out


def test_s04p_a_share_truncates_to_5_years():
    rows = [
        {
            "REPORT_DATE": f"{y}-12-31",
            "TOTAL_ASSETS": 1e11,
            "TOTAL_LIABILITIES": 5e10,
            "TOTAL_EQUITY": 5e10,
            "MONETARY_FUND": 1e10,
            "LONG_EQUITY_INVEST": 1e10,
        }
        for y in [2025, 2024, 2023, 2022, 2021, 2020]
    ]
    s = MagicMock()
    s.query_financial_for_section.return_value = rows
    out = s04p_parent_balance.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=s,
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "2025-12-31" in out and "2021-12-31" in out
    assert "2020-12-31" not in out
