"""验证 MockContext 自身的语义,作为后续 utils 测试的基础设施。"""

import pandas as pd
from tests.utils_test_helpers import MockContext


def test_get_dividend_returns_injected_df():
    df = pd.DataFrame({"现金分红-现金分红比例": [3.62], "报告期": ["2023-12-31"]})
    ctx = MockContext(dividend={"000001.SZ": df})
    assert ctx.get_dividend("000001.SZ") is df
    assert ctx.get_dividend("999999.SZ") is None


def test_get_financial_returns_injected_dict():
    ctx = MockContext(financial={"000001.SZ": {"净资产收益率": 14.7}})
    assert ctx.get_financial("000001.SZ") == {"净资产收益率": 14.7}


def test_get_valuation_returns_injected_dict():
    ctx = MockContext(
        valuation={"000001.SZ": {"pe_ttm": 5.2, "pb": 0.7, "total_mv": 4.5e11}}
    )
    val = ctx.get_valuation("000001.SZ")
    assert val["pe_ttm"] == 5.2


def test_get_history_returns_injected_list_capped_by_n():
    bars = [
        {
            "date": f"2024-{m:02d}-01",
            "close": 10.0 + m,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "volume": 1000,
        }
        for m in range(1, 13)
    ]
    ctx = MockContext(history={"000001.SZ": bars})
    h = ctx.get_history("000001.SZ", 5)
    assert len(h) == 5
    assert h[-1]["date"] == "2024-12-01"


def test_log_pass_records_calls():
    ctx = MockContext()
    ctx.log_pass("000001.SZ", "dividend.years", years=12)
    ctx.log_pass("000002.SZ", "dividend.years", years=8)
    assert len(ctx.pass_logs) == 2
    assert ctx.pass_logs[0] == ("000001.SZ", "dividend.years", {"years": 12})


def test_log_reject_records_calls():
    ctx = MockContext()
    ctx.log_reject("600519.SH", "dividend.years", reason="below_threshold", years=3)
    assert ctx.reject_logs[0] == (
        "600519.SH",
        "dividend.years",
        "below_threshold",
        {"years": 3},
    )


def test_log_flow_records_calls():
    ctx = MockContext()
    ctx.log_flow("dividend.years", input=4823, passed=421)
    assert ctx.flow_logs[0] == ("dividend.years", {"input": 4823, "passed": 421})


def test_current_date_and_idx_default():
    ctx = MockContext()
    assert ctx.current_date is None
    assert ctx.current_idx == 0


def test_current_date_can_be_set():
    ctx = MockContext(current_date="2024-03-29", current_idx=42)
    assert ctx.current_date == "2024-03-29"
    assert ctx.current_idx == 42
