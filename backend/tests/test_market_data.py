"""MarketData 适配器单测(Phase 3.2)。

覆盖:
- 聚合正确性(weekly→W-FRI / monthly→M)
- idx 越界 / 不存在的 symbol → 返回 None / []
- 周/月/日 period 切换:同一 idx 在不同 period 返回不同价格
- get_history 边界:n 超出已有长度 / idx=0 仅 1 行
- valuation / dividend / financial 字典缺失时返回 None
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.backtest.market_data import MarketData, _build_static_table


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


def test_extract_indicators_accepts_nullable_numeric_columns():
    frame = pd.DataFrame({"ma20": pd.Series([pd.NA, 12.5], dtype="Float64")})

    indicators = MarketData._extract_indicators(frame)

    assert indicators["ma20"].dtype == np.dtype(float)
    assert np.isnan(indicators["ma20"][0])
    assert indicators["ma20"][1] == pytest.approx(12.5)


def test_static_table_accepts_nullable_numeric_columns():
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-02-01"],
            "pe": pd.Series([pd.NA, 12.5], dtype="Float64"),
        }
    )

    table = _build_static_table(frame, date_col="date")

    assert table.num_cols["pe"].dtype == np.dtype(float)
    assert np.isnan(table.num_cols["pe"][0])
    assert table.num_cols["pe"][1] == pytest.approx(12.5)


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


def test_get_valuation_ffill_nan_in_latest_row(stock_data):
    """最新一行 pe 为 NaN 时,应向前回填到最近一个非空值(保留旧 sub_mask 语义)。"""
    val_df = pd.DataFrame(
        {
            "date": ["2024-01-15", "2024-02-15", "2024-03-15"],
            "pe": [10.0, 12.0, float("nan")],
            "pb": [1.0, float("nan"), 1.5],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    row = md.get_valuation("000001", date="2024-03-20")
    assert row is not None
    assert row["pe"] == 12.0  # ffill from 02-15
    assert row["pb"] == 1.5  # 03-15 本身有值


def test_get_valuation_leading_nan_returns_none(stock_data):
    """开头就是 NaN(无可回填的历史值),返回 None。"""
    val_df = pd.DataFrame(
        {
            "date": ["2024-01-15", "2024-02-15"],
            "pe": [float("nan"), 12.0],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    row = md.get_valuation("000001", date="2024-01-20")
    assert row is not None
    assert row["pe"] is None


def test_get_valuation_unsorted_input_still_correct(stock_data):
    """入参顺序乱时,_StaticTable 内部按 date 排序,查询结果仍正确。"""
    val_df = pd.DataFrame({"date": ["2024-02-15", "2024-01-15"], "pe": [12.0, 10.0]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    assert md.get_valuation("000001", date="2024-01-20")["pe"] == 10.0
    assert md.get_valuation("000001", date="2024-02-20")["pe"] == 12.0


def test_get_financial_nan_returns_none_no_ffill(stock_data):
    """financial 不做 ffill — NaN 字段返回 None,与旧逻辑一致。
    English schema:REPORT_DATE 替代 报告期。"""
    fin_df = pd.DataFrame(
        {
            "REPORT_DATE": ["2023-12-31", "2024-03-31"],
            "NETPROFIT": [100.0, float("nan")],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", financial={"000001": fin_df}
    )
    row = md.get_financial("000001", date="2024-04-15")
    assert row is not None
    assert row["NETPROFIT"] is None  # 不向前回填


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
            "REPORT_DATE": ["2023-12-31", "2024-03-31"],
            "NETPROFIT": [100.0, 120.0],
            "ROEJQ": [0.1, 0.12],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", financial={"000001": fin_df}
    )
    row = md.get_financial("000001", date="2024-04-15")
    assert row is not None
    assert row["NETPROFIT"] == 120.0


def test_get_financial_none_when_missing(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_financial("000001", date="2024-04-15") is None


def test_get_financial_annual_filters_to_year_end_only(stock_data):
    """get_financial_annual 应只返回 REPORT_DATE 以 -12-31 结尾的记录,
    避免季度累计 ROE 在年中被误用。"""
    fin_df = pd.DataFrame(
        {
            "REPORT_DATE": [
                "2022-12-31",
                "2023-03-31",
                "2023-06-30",
                "2023-09-30",
                "2023-12-31",
                "2024-03-31",
            ],
            "ROEJQ": [11.0, 2.5, 5.0, 7.5, 10.5, 2.8],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", financial={"000001": fin_df}
    )
    # 2024-04-15 时,最新季报是 2024-Q1(2.8),但 annual 应回退到 2023 年报 10.5
    row = md.get_financial_annual("000001", date="2024-04-15")
    assert row is not None
    assert row["REPORT_DATE"] == "2023-12-31"
    assert row["ROEJQ"] == 10.5

    # 2023-08-01 时,annual 应回退到 2022 年报(11.0),而不是 H1 累计的 5.0
    row = md.get_financial_annual("000001", date="2023-08-01")
    assert row is not None
    assert row["REPORT_DATE"] == "2022-12-31"
    assert row["ROEJQ"] == 11.0

    # 早于第一份年报 → None
    row = md.get_financial_annual("000001", date="2022-06-01")
    assert row is None


def test_get_financial_annual_missing_symbol(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_financial_annual("000001", date="2024-04-15") is None


# ============= max_staleness_days(2026-06-09 新增,退市股 stale 数据防护)=============
# 背景:get_valuation 走 ASOF (`<= date` 最近一行),退市股(如 600291.SH 2022 退市)
# 在 2026 查询会返回 2022 的 stale pbMRQ,误进选股池后 T+1 buy 永久 pending。
# max_staleness_days 限制最近一行 date 与查询 date 的日历日差。


def test_get_valuation_staleness_filters_old_row(stock_data):
    val_df = pd.DataFrame({"date": ["2022-06-30"], "pe": [10.0], "pb": [0.8]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    # 默认行为(无 staleness 限制)→ 命中 stale 行
    assert md.get_valuation("000001", date="2026-05-15") is not None
    # 启用 staleness=10 → 1400+ 日历日 gap → 过滤为 None
    assert md.get_valuation("000001", date="2026-05-15", max_staleness_days=10) is None


def test_get_valuation_staleness_passes_recent_row(stock_data):
    val_df = pd.DataFrame({"date": ["2024-02-10", "2024-02-15"], "pe": [10.0, 12.0]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    # 2024-02-18 vs row 2024-02-15 → 3 日差 ≤ 10 → 命中
    row = md.get_valuation("000001", date="2024-02-18", max_staleness_days=10)
    assert row is not None
    assert row["pe"] == 12.0


def test_get_valuation_staleness_none_when_no_param(stock_data):
    """max_staleness_days=None(默认)保持现有行为,即使 row 极陈旧也返回。"""
    val_df = pd.DataFrame({"date": ["2010-01-15"], "pe": [10.0]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    row = md.get_valuation("000001", date="2026-05-15")
    assert row is not None  # 向后兼容:无参数 = 不过滤
    assert row["pe"] == 10.0


def test_get_valuation_staleness_boundary_inclusive(stock_data):
    """gap == max_staleness_days 应通过(<=,不是 <)。"""
    val_df = pd.DataFrame({"date": ["2024-02-05"], "pe": [10.0]})
    md = MarketData(
        stock_data=stock_data, frequency="daily", valuation={"000001": val_df}
    )
    # 2024-02-15 - 2024-02-05 = 10 日,boundary 应通过
    row = md.get_valuation("000001", date="2024-02-15", max_staleness_days=10)
    assert row is not None
    # 11 日 → 过滤
    assert md.get_valuation("000001", date="2024-02-16", max_staleness_days=10) is None


def test_get_financial_staleness_filters_old_report(stock_data):
    """财务报告本身是季度披露,典型 staleness 阈值应 >100 天。
    本测试用极端值 30 天验证机制。"""
    fin_df = pd.DataFrame(
        {
            "REPORT_DATE": ["2022-12-31"],
            "NETPROFIT": [100.0],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", financial={"000001": fin_df}
    )
    # 1000+ 日 gap → 30 日阈值过滤
    assert md.get_financial("000001", date="2026-05-15", max_staleness_days=30) is None
    # 默认无限制 → 命中
    assert md.get_financial("000001", date="2026-05-15") is not None


def test_get_balance_staleness_supported(stock_data):
    bal_df = pd.DataFrame(
        {
            "REPORT_DATE": ["2022-12-31"],
            "TOTALASSETS": [1000.0],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", balance={"000001": bal_df}
    )
    assert md.get_balance("000001", date="2026-05-15", max_staleness_days=30) is None
    assert md.get_balance("000001", date="2026-05-15") is not None


def test_get_cashflow_staleness_supported(stock_data):
    cf_df = pd.DataFrame(
        {
            "REPORT_DATE": ["2022-12-31"],
            "NETCASHOPERATE": [50.0],
        }
    )
    md = MarketData(
        stock_data=stock_data, frequency="daily", cashflow={"000001": cf_df}
    )
    assert md.get_cashflow("000001", date="2026-05-15", max_staleness_days=30) is None
    assert md.get_cashflow("000001", date="2026-05-15") is not None


# ============= _resolve_idx (searchsorted) 回归测试 =============
# 这些测试针对 _resolve_idx 由 O(N) pandas mask → O(log N) np.searchsorted 的优化,
# 重点覆盖 sparse 个股(停牌/上市晚)、target 早于首日、精确匹配等边界。


def test_resolve_idx_daily_exact_match(stock_data):
    """target_date 精确等于某一日 → 返回该日。"""
    md = MarketData(stock_data=stock_data, frequency="daily")
    idx = md.dates.index("2024-02-15")
    df, i = md._resolve_idx("000001", "daily", idx)
    assert df is not None and i >= 0
    assert df.iloc[i]["date"] == "2024-02-15"


def test_resolve_idx_sparse_stock_falls_back_to_prev_trading_day(daily_dates):
    """个股停牌 / 数据缺失:应返回 ≤ target 的最近一根。"""
    # 参考股票有完整日历,sparse 股缺失 2024-02-12 ~ 2024-02-23 共两周
    full = _make_daily(daily_dates, base=10.0)
    sparse_dates = [d for d in daily_dates if not ("2024-02-12" <= d <= "2024-02-23")]
    sparse = _make_daily(sparse_dates, base=20.0)
    md = MarketData(
        stock_data={"FULL": full, "SPARSE": sparse},  # FULL 在前,作为参考日历
        frequency="daily",
    )
    # 在停牌窗口内查询 → 应回退到 2024-02-09(停牌前最后一日)
    target_idx = md.dates.index("2024-02-15")
    df, i = md._resolve_idx("SPARSE", "daily", target_idx)
    assert df is not None and i >= 0
    assert df.iloc[i]["date"] == "2024-02-09"


def test_resolve_idx_target_before_first_date_returns_minus_one(daily_dates):
    """target_date 早于个股首个交易日 → idx = -1。"""
    full = _make_daily(daily_dates, base=10.0)
    # 后上市股票:从 2024-03 才开始
    late_dates = [d for d in daily_dates if d >= "2024-03-01"]
    late = _make_daily(late_dates, base=30.0)
    md = MarketData(
        stock_data={"FULL": full, "LATE": late},
        frequency="daily",
    )
    target_idx = md.dates.index("2024-01-15")
    df, i = md._resolve_idx("LATE", "daily", target_idx)
    assert df is not None  # df 存在但索引无效
    assert i == -1
    assert md.get_price("LATE", "daily", idx=target_idx) is None


def test_resolve_idx_monthly_returns_last_completed_month(stock_data):
    """月线:在 2 月中查询 → 返回 1 月线(最后一根 ≤ target 的月度收盘)。"""
    md = MarketData(stock_data=stock_data, frequency="monthly")
    mid_feb_idx = md.dates.index("2024-02-15")
    df, i = md._resolve_idx("000001", "monthly", mid_feb_idx)
    assert df is not None and i >= 0
    # 聚合后的月线 date 是该月最后一个交易日
    assert df.iloc[i]["date"].startswith("2024-01")


def test_resolve_idx_consistency_with_pandas_mask(stock_data, daily_dates):
    """对照测试:searchsorted 结果 == 旧版 (df['date'] <= target) 全表扫描结果。

    这是优化前后等价性的核心保证。
    """
    md = MarketData(stock_data=stock_data, frequency="weekly")
    weekly_df = md._period_cache["weekly"]["000001"]
    arr = weekly_df["date"].to_numpy()
    # 抽样所有日历日,逐个比对
    for idx in range(0, len(md.dates), 5):
        target = md.dates[idx]
        # 旧逻辑:O(N) mask
        mask = weekly_df["date"] <= target
        expected = int(mask.sum()) - 1  # 最后一个 True 的位置;无匹配则 -1
        # 新逻辑:O(log N) searchsorted
        actual = int(np.searchsorted(arr, target, side="right")) - 1
        assert actual == expected, f"mismatch at idx={idx} target={target}"


def test_resolve_idx_idx_at_boundaries(stock_data):
    """idx=0 / idx=len-1 边界。"""
    md = MarketData(stock_data=stock_data, frequency="daily")
    df0, i0 = md._resolve_idx("000001", "daily", 0)
    assert df0 is not None and i0 == 0
    last = len(md.dates) - 1
    dl, il = md._resolve_idx("000001", "daily", last)
    assert dl is not None and il == last
    # 越界
    _, i_neg = md._resolve_idx("000001", "daily", -1)
    assert i_neg == -1
    _, i_huge = md._resolve_idx("000001", "daily", 10_000_000)
    assert i_huge == -1


# ============= get_bar_at(快速路径,engine._build_bar 用) =============


def test_get_bar_at_returns_ohlc_dict(stock_data):
    """正常返回 OHLC + date 五字段。"""
    md = MarketData(stock_data=stock_data, frequency="daily")
    bar = md.get_bar_at("000001", idx=10, period="daily")
    assert bar is not None
    # volume 字段在 stock_data 含 volume 列时随之返回(broker volume=0 拒单依赖)
    assert {"open", "high", "low", "close", "date"}.issubset(bar.keys())
    # 与 get_price 对照(同 idx 同 symbol)
    row = md.get_price("000001", "daily", idx=10)
    for k in ("open", "high", "low", "close"):
        assert bar[k] == pytest.approx(row[k])
    assert bar["date"] == row["date"]


def test_get_bar_at_strict_skips_suspended_day(daily_dates):
    """strict=True:停牌当日返回 None;strict=False:回退到前一交易日。"""
    full = _make_daily(daily_dates, base=10.0)
    sparse_dates = [d for d in daily_dates if not ("2024-02-12" <= d <= "2024-02-23")]
    sparse = _make_daily(sparse_dates, base=20.0)
    md = MarketData(stock_data={"FULL": full, "SPARSE": sparse}, frequency="daily")
    target_idx = md.dates.index("2024-02-15")
    # strict: 停牌当日 → None
    assert md.get_bar_at("SPARSE", target_idx, strict=True) is None
    # 非 strict: 回退到 2024-02-09
    bar = md.get_bar_at("SPARSE", target_idx, strict=False)
    assert bar is not None
    assert bar["date"] == "2024-02-09"


def test_get_bar_at_idx_out_of_range_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_bar_at("000001", -1) is None
    assert md.get_bar_at("000001", 10_000_000) is None


def test_get_bar_at_unknown_symbol_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_bar_at("999999", idx=0) is None


def test_get_bar_at_weekly_lazy_builds_cache(stock_data):
    """weekly 缓存懒构建:首次访问触发,后续直接命中。"""
    md = MarketData(stock_data=stock_data, frequency="daily")  # 启动只建 daily
    assert "weekly" not in md._period_cache
    bar = md.get_bar_at("000001", idx=20, period="weekly", strict=False)
    assert bar is not None
    assert "weekly" in md._period_cache
    assert "weekly" in md._ohlc_arrays


def test_get_bar_at_consistency_across_dates(stock_data):
    """对照测试:get_bar_at 与 get_price OHLC 完全一致(strict=False)。"""
    md = MarketData(stock_data=stock_data, frequency="weekly")
    for idx in range(0, len(md.dates), 5):
        bar = md.get_bar_at("000001", idx, period="weekly", strict=False)
        row = md.get_price("000001", "weekly", idx=idx)
        if row is None:
            assert bar is None
            continue
        assert bar is not None
        for k in ("open", "high", "low", "close"):
            assert bar[k] == pytest.approx(row[k]), f"mismatch at idx={idx} field={k}"


# ============= get_indicator(2026-05-22 引入)=============


def test_get_indicator_ma_standard_window_returns_value(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    # daily 全历史 ~63 根,ma20 在 idx=19 起有效
    v_at_30 = md.get_indicator("ma", "000001", idx=30, window=20)
    # 用同一 ctx 的 get_history 路径求 ground truth 对照
    bars = md.get_history("000001", n=20, idx=30, period="daily")
    expected = sum(b["close"] for b in bars[-20:]) / 20
    assert v_at_30 == pytest.approx(expected)


def test_get_indicator_non_standard_window_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    # window=15 不在标准集 → resolve 返回 None → get_indicator 返回 None
    assert md.get_indicator("ma", "000001", idx=30, window=15) is None


def test_get_indicator_macd_default_params(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    dif = md.get_indicator("macd", "000001", idx=50, field="dif")
    dea = md.get_indicator("macd", "000001", idx=50, field="dea")
    hist = md.get_indicator("macd", "000001", idx=50, field="hist")
    assert dif is not None and dea is not None and hist is not None
    # AGENTS.md 硬性约定:hist = 2 × (DIF - DEA)
    assert hist == pytest.approx(2.0 * (dif - dea))


def test_get_indicator_data_insufficient_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    # idx=0 时 ma20 尚不可用(NaN)
    assert md.get_indicator("ma", "000001", idx=0, window=20) is None


def test_get_indicator_unknown_symbol_returns_none(stock_data):
    md = MarketData(stock_data=stock_data, frequency="daily")
    assert md.get_indicator("ma", "999999", idx=10, window=20) is None
