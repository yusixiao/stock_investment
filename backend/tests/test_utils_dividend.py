import pandas as pd
from tests.utils_test_helpers import MockContext
from services.backtest.strategies.utils import dividend


def _div_df(rows):
    """rows: list of (date, cash_dividend) — English schema(2026-05-21)"""
    return pd.DataFrame(
        {
            "date": [r[0] for r in rows],
            "cash_dividend": [r[1] for r in rows],
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
    df = pd.DataFrame({"date": ["2020-12-31"]})
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") is None


def test_count_dividend_years_memoized_via_df_attrs():
    """同一 df 多次调用应命中 df.attrs 缓存(Round 4 性能优化)。"""
    df = _div_df([("2020-12-31", 1.0), ("2021-12-31", 2.0)])
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") == 2
    # 缓存键已写入 df.attrs
    assert df.attrs.get("_count_dividend_years_cache") == 2
    # 再次调用直接从 attrs 取(即使我们偷偷篡改 df 数据,结果也保持第一次的值)
    df.loc[len(df)] = ["2022-12-31", 3.0]
    assert dividend.count_dividend_years(ctx, "A") == 2  # cached


def test_count_dividend_years_missing_column_memoized_as_none():
    """列缺失情形也应 memoize,避免重复列检查。"""
    df = pd.DataFrame({"date": ["2020-12-31"]})
    ctx = MockContext(dividend={"A": df})
    assert dividend.count_dividend_years(ctx, "A") is None
    # sentinel = -1 表示「应返回 None」
    assert df.attrs.get("_count_dividend_years_cache") == -1
    assert dividend.count_dividend_years(ctx, "A") is None  # 仍 None


def test_count_dividend_years_different_dfs_independent_cache():
    """不同 symbol 的 df 各自独立缓存,不会串味。"""
    df_a = _div_df([("2020-12-31", 1.0)])
    df_b = _div_df([("2020-12-31", 1.0), ("2021-12-31", 1.0), ("2022-12-31", 1.0)])
    ctx = MockContext(dividend={"A": df_a, "B": df_b})
    assert dividend.count_dividend_years(ctx, "A") == 1
    assert dividend.count_dividend_years(ctx, "B") == 3
    # 各自的 attrs 互不干扰
    assert df_a.attrs.get("_count_dividend_years_cache") == 1
    assert df_b.attrs.get("_count_dividend_years_cache") == 3


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
