"""MarketData 适配器单测(Phase 3.2)。

覆盖:
- 聚合正确性(weekly→W-FRI / monthly→M)
- idx 越界 / 不存在的 symbol → 返回 None / []
- 周/月/日 period 切换:同一 idx 在不同 period 返回不同价格
- get_history 边界:n 超出已有长度 / idx=0 仅 1 行
- valuation / dividend / financial 字典缺失时返回 None
"""

from __future__ import annotations

import pandas as pd
import pytest

from services.backtest.market_data import MarketData


def _make_daily(dates: list[str], base: float = 10.0) -> pd.DataFrame:
    """构造一个 7 列、日期升序的日线 DataFrame。"""
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "open": [base + i for i in range(n)],
            "high": [base + i + 0.5 for i in range(n)],
            "low": [base + i - 0.5 for i in range(n)],
            "close": [base + i + 0.2 for i in range(n)],
            "volume": [1000.0 + i for i in range(n)],
            "amount": [10000.0 + i for i in range(n)],
        }
    )


@pytest.fixture
def daily_dates() -> list[str]:
    # ~3 个月日历日(只保留工作日,简化为顺序日期)
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-02", "2024-03-29")]


@pytest.fixture
def stock_data(daily_dates) -> dict[str, pd.DataFrame]:
    return {
        "000001": _make_daily(daily_dates, base=10.0),
        "600000": _make_daily(daily_dates, base=20.0),
    }


# ============= dates 时间轴 =============


def test_dates_align_to_reference_symbol_calendar(stock_data, daily_dates):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.dates == daily_dates


def test_dates_sorted_ascending_even_if_input_descending(daily_dates):
    desc = (
        _make_daily(daily_dates)
        .sort_values("date", ascending=False)
        .reset_index(drop=True)
    )
    md = MarketData(stock_data={"000001": desc}, frequency="daily")
    assert md.dates == daily_dates


# ============= get_price =============


def test_get_price_daily_returns_row_at_idx(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    row = md.get_price("000001", period="daily", idx=0)
    assert row is not None
    assert row["date"] == md.dates[0]
    assert row["close"] == pytest.approx(10.2)


def test_get_price_idx_out_of_range_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_price("000001", period="daily", idx=-1) is None
    assert md.get_price("000001", period="daily", idx=10_000) is None


def test_get_price_unknown_symbol_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_price("999999", period="daily", idx=0) is None


def test_get_price_weekly_aggregates_to_w_fri(stock_data):
    md = MarketData(stock_data=stock_data, frequency="weekly")
    # 周聚合后,某一日的周线 close == 该周最后一根日线的 close
    last_idx = len(md.dates) - 1
    daily_close = md.get_price("000001", period="daily", idx=last_idx)["close"]
    weekly_close = md.get_price("000001", period="weekly", idx=last_idx)["close"]
    # 当 last_idx 落在某周最后一日,二者应一致;否则周线值落后
    assert weekly_close <= daily_close + 1e-9


def test_get_price_monthly_aggregates_to_three_periods(stock_data):
    md = MarketData(stock_data=stock_data, frequency="monthly")
    # 1 月底应该可以拿到第一个月的月线
    jan_end_idx = md.dates.index("2024-01-31")
    row = md.get_price("000001", period="monthly", idx=jan_end_idx)
    assert row is not None
    # 月线 high == 该月所有日线 high 最大值
    daily_df = stock_data["000001"]
    jan_mask = daily_df["date"].str.startswith("2024-01")
    assert row["high"] == pytest.approx(daily_df.loc[jan_mask, "high"].max())
    assert row["low"] == pytest.approx(daily_df.loc[jan_mask, "low"].min())


def test_period_switch_returns_different_prices(stock_data):
    """同一 idx 上,daily / weekly / monthly 拿到的 close 一般不同。"""
    md = MarketData(stock_data=stock_data, frequency="monthly")
    idx = md.dates.index("2024-02-15")
    d = md.get_price("000001", period="daily", idx=idx)["close"]
    w = md.get_price("000001", period="weekly", idx=idx)["close"]
    m = md.get_price("000001", period="monthly", idx=idx)["close"]
    # weekly/monthly 是「截至当前的最后一个完成周期」的 close,落后于 daily
    assert d >= w >= m  # 由于 close 单调递增构造,周/月线 close <= daily


# ============= get_history =============


def test_get_history_returns_n_rows(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    rows = md.get_history("000001", n=5, period="daily", idx=10)
    assert len(rows) == 5
    # 升序排列,最后一行 == idx 处的 bar
    assert rows[-1]["date"] == md.dates[10]


def test_get_history_idx_zero_returns_single_row(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    rows = md.get_history("000001", n=10, period="daily", idx=0)
    assert len(rows) == 1
    assert rows[0]["date"] == md.dates[0]


def test_get_history_n_exceeds_available_clips(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    rows = md.get_history("000001", n=999, period="daily", idx=3)
    assert len(rows) == 4  # 0..3


def test_get_history_idx_out_of_range_returns_empty(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_history("000001", n=5, period="daily", idx=-1) == []
    assert md.get_history("000001", n=5, period="daily", idx=10_000) == []


def test_get_history_unknown_symbol_returns_empty(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_history("999999", n=5, period="daily", idx=0) == []


def test_get_history_monthly(stock_data):
    md = MarketData(stock_data=stock_data, frequency="monthly")
    feb_end = md.dates.index("2024-02-29")
    rows = md.get_history("000001", n=2, period="monthly", idx=feb_end)
    # 截至 2 月底应有 1 月、2 月共 2 根月线
    assert len(rows) == 2
    assert rows[0]["date"].startswith("2024-01")
    assert rows[1]["date"].startswith("2024-02")


# ============= valuation / dividend / financial =============


def test_get_valuation_none_when_dict_missing(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_valuation("000001", date="2024-02-15") is None


def test_get_valuation_returns_latest_on_or_before_date(stock_data):
    val_df = pd.DataFrame(
        {"date": ["2024-01-15", "2024-02-15"], "pe": [10.0, 12.0], "pb": [1.0, 1.2]}
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    row = md.get_valuation("000001", date="2024-02-20")
    assert row is not None
    assert row["pe"] == 12.0


def test_get_valuation_none_before_first_record(stock_data):
    val_df = pd.DataFrame({"date": ["2024-02-15"], "pe": [12.0]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    assert md.get_valuation("000001", date="2024-01-01") is None


def test_get_dividend_returns_df_when_present(stock_data):
    div_df = pd.DataFrame({"ex_date": ["2024-02-15"], "dividend": [0.5]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", dividend={"000001": div_df}
    )
    out = md.get_dividend("000001", date="2024-03-01")
    assert out is not None
    assert len(out) == 1


def test_get_dividend_none_when_missing(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_dividend("000001", date="2024-03-01") is None


def test_get_financial_returns_latest_on_or_before_date(stock_data):
    fin_df = pd.DataFrame(
        {
            "报告期": ["2023-12-31", "2024-03-31"],
            "净利润": [100.0, 120.0],
            "ROE": [0.1, 0.12],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", financial={"000001": fin_df}
    )
    row = md.get_financial("000001", date="2024-04-15")
    assert row is not None
    assert row["净利润"] == 120.0


def test_get_financial_none_when_missing(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_financial("000001", date="2024-04-15") is None
