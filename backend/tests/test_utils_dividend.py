import pandas as pd
from tests.utils_test_helpers import MockContext
from strategies.utils import dividend


def _div_df(rows):
    """rows: list of (报告期, 现金分红-现金分红比例)"""
    return pd.DataFrame(
        {
            "报告期": [r[0] for r in rows],
            "现金分红-现金分红比例": [r[1] for r in rows],
        }
    )


def test_count_dividend_years_basic():
    df = _div_df([("2020-12-31", 3.0), ("2021-12-31", 2.5), ("2022-12-31", 1.8)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 3


def test_count_dividend_years_dedupes_same_year():
    df = _div_df([("2020-06-30", 1.0), ("2020-12-31", 2.0), ("2021-12-31", 1.5)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 2


def test_count_dividend_years_skips_zero_or_negative():
    df = _div_df([("2020-12-31", 0.0), ("2021-12-31", 2.5)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 1


def test_count_dividend_years_skips_nan():
    df = _div_df([("2020-12-31", float("nan")), ("2021-12-31", 2.5)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 1


def test_count_dividend_years_no_data_returns_none():
    ctx = MockContext()
    assert dividend.count_dividend_years(ctx, "A") is None


def test_count_dividend_years_missing_column_returns_none():
    df = pd.DataFrame({"报告期": ["2020-12-31"]})
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") is None


def test_filter_by_dividend_years_pass_and_reject():
    pass_df = _div_df([(f"{y}-12-31", 1.0) for y in range(2018, 2024)])  # 6 年
    fail_df = _div_df([(f"{y}-12-31", 1.0) for y in range(2022, 2024)])  # 2 年
    ctx = MockContext(dividend={"P": pass_df, "F": fail_df})

    result = dividend.filter_by_dividend_years(ctx, ["P", "F"], min_years=5)

    assert result == ["P"]
    assert ctx.pass_logs == [("P", "dividend.years", {"years": 6, "threshold": 5})]
    assert ctx.reject_logs == [
        ("F", "dividend.years", "below_threshold", {"years": 2, "threshold": 5})
    ]


def test_filter_by_dividend_years_no_data_rejects_with_reason_no_data():
    ctx = MockContext()  # 无注入
    result = dividend.filter_by_dividend_years(ctx, ["X"], min_years=5)
    assert result == []
    assert ctx.reject_logs == [("X", "dividend.years", "no_data", {"threshold": 5})]


def test_filter_by_dividend_years_logs_flow_summary():
    pass_df = _div_df([(f"{y}-12-31", 1.0) for y in range(2018, 2024)])
    ctx = MockContext(dividend={"P": pass_df})
    dividend.filter_by_dividend_years(ctx, ["P", "X"], min_years=5)
    assert ctx.flow_logs == [("dividend.years", {"input": 2, "passed": 1})]
