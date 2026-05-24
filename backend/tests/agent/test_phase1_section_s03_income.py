"""问股期 1 — Task 22:§3 利润表测试。"""

from unittest.mock import MagicMock

from services.agent.pipeline.phase1_data_pack.sections import s03_income
from services.agent.symbol import StockRef


def _store(rows):
    s = MagicMock()
    s.query_financial.return_value = rows
    return s


def test_section_3_basic():
    rows = [
        {
            "REPORT_DATE": "2025-12-31",
            "TOTAL_OPERATE_INCOME": 7.7e11,
            "OPERATE_COST": 6.2e11,
            "GROSS_PROFIT": 1.5e11,
            "OPERATE_PROFIT": 3.0e10,
            "NETPROFIT": 3.5e10,
            "PARENT_NETPROFIT": 3.4e10,
            "DEDUCT_PARENT_NETPROFIT": 3.0e10,
            "BASIC_EPS": 11.7,
        },
        {
            "REPORT_DATE": "2024-12-31",
            "TOTAL_OPERATE_INCOME": 6.0e11,
            "OPERATE_COST": 4.9e11,
            "GROSS_PROFIT": 1.1e11,
            "OPERATE_PROFIT": 2.5e10,
            "NETPROFIT": 3.0e10,
            "PARENT_NETPROFIT": 2.9e10,
            "DEDUCT_PARENT_NETPROFIT": 2.7e10,
            "BASIC_EPS": 10.0,
        },
    ]
    out = s03_income.build(
        StockRef("002594.SZ", "比亚迪", "A"),
        store=_store(rows),
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "## §3 利润表" in out
    assert "2025-12-31" in out and "2024-12-31" in out
    assert "770,000" in out  # 7.7e11/1e6
    assert "扣非归母净利润" in out
    assert "11.70" in out  # EPS


def test_section_3_empty_emits_warning():
    out = s03_income.build(
        StockRef("X", "x", "A"),
        store=_store([]),
        stock_index=MagicMock(),
        indicators=MagicMock(),
    )
    assert "数据缺失" in out
