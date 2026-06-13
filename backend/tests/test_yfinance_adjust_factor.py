"""YFinanceAdapter.fetch_adjust_factor — 同除权日多事件聚合测试。

背景(2026-06 根因修复):
同一除权日可能同时发生多个公司行为(如分红+拆股)。旧实现把分红与拆股
事件混入同一 events 列表后直接从后往前累乘,**未按日期合并**,导致同一
dividOperateDate 产出多条因子不同的行。写入 parquet 后该日键非唯一,
qfq ASOF JOIN 在并行执行下随机选行 → 复权价跨进程不同 → 回测不可复现。

修复:累乘前先把同日所有 factor_change 连乘合并成一个,每个除权日只产 1 行。

测试覆盖:
1. 同日 分红+正向拆股(change<1) → 单行 + 因子=连乘
2. 同日 分红+反向拆股(change>1,合股) → 单行 + 正确传播(证明是连乘合并,
   而非 max/min/first/last 去重)
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from backend.adapters.yfinance_adapter import YFinanceAdapter


def _make_ticker(hist: pd.DataFrame, divs: pd.Series, splits: pd.Series):
    """构造伪 Ticker,绕过真实 yfinance 网络调用。"""

    class FakeTicker:
        def __init__(self, *a, **kw):
            pass

        def history(self, *a, **kw):
            return hist

        @property
        def dividends(self):
            return divs

        @property
        def splits(self):
            return splits

    return FakeTicker


def _run(hist, divs, splits):
    fake = _make_ticker(hist, divs, splits)
    with patch("backend.adapters.yfinance_adapter.yf.Ticker", fake):
        return YFinanceAdapter().fetch_adjust_factor("00036.HK")


def test_same_day_dividend_and_forward_split_merged():
    """同日分红(0.90)+ 2:1 拆股(0.50)→ 合并 change=0.45,每日唯一一行。"""
    hist = pd.DataFrame(
        {"Close": [100.0, 100.0, 100.0, 50.0]},
        index=pd.to_datetime(
            ["2020-05-29", "2020-06-01", "2022-05-19", "2022-05-20"]
        ),
    )
    # 2020-06-01: prev_close=100, amount=5 → 0.95(最早事件,自身 change 不参与)
    # 2022-05-20: prev_close=100, amount=10 → 0.90
    divs = pd.Series(
        [5.0, 10.0],
        index=pd.to_datetime(["2020-06-01", "2022-05-20"]),
    )
    # 2022-05-20: 2:1 拆股 → change = 1/2 = 0.50
    splits = pd.Series([2.0], index=pd.to_datetime(["2022-05-20"]))

    records = _run(hist, divs, splits)

    dates = [r.dividOperateDate for r in records]
    # 每个除权日只产一行(修复前 2022-05-20 会出两行)
    assert len(dates) == len(set(dates))
    assert dates == ["2020-06-01", "2022-05-20"]

    by_date = {r.dividOperateDate: r.foreAdjustFactor for r in records}
    # 最新事件锚定为 1.0
    assert by_date["2022-05-20"] == 1.0
    # 2020-06-01 = 1.0 × 合并 change(0.90 × 0.50 = 0.45)
    assert by_date["2020-06-01"] == 0.45


def test_same_day_dividend_and_reverse_split_merged():
    """同日分红 + 1:10 合股(change=10>1)→ 连乘合并,正确向更早日期传播。

    若用 max/min/first/last 去重而非连乘合并,2016-03-01 因子会算错。

    注:Close 必须如实反映 1:10 合股的 ×10 跳空(2018-01-12 的 10 → 2018-01-15 的 100),
    否则会被幻灵拆股审计(audit_factors)判为虚假事件并中性化。这正是真实合股的样子。
    """
    hist = pd.DataFrame(
        {"Close": [10.0, 10.0, 10.0, 100.0, 100.0, 100.0]},
        index=pd.to_datetime(
            [
                "2016-02-26",
                "2016-03-01",
                "2018-01-12",
                "2018-01-15",  # 1:10 合股,价格 ×10 跳空
                "2020-05-29",
                "2020-06-01",
            ]
        ),
    )
    divs = pd.Series(
        [2.0, 2.0, 5.0],
        index=pd.to_datetime(["2016-03-01", "2018-01-15", "2020-06-01"]),
    )
    # 2018-01-15: 1:10 反向拆股 → yfinance ratio=0.1 → change = 1/0.1 = 10.0
    splits = pd.Series([0.1], index=pd.to_datetime(["2018-01-15"]))

    records = _run(hist, divs, splits)

    dates = [r.dividOperateDate for r in records]
    assert len(dates) == len(set(dates))
    assert dates == ["2016-03-01", "2018-01-15", "2020-06-01"]

    by_date = {r.dividOperateDate: r.foreAdjustFactor for r in records}
    # 最新事件锚定 1.0
    assert by_date["2020-06-01"] == 1.0
    # 2018-01-15 = 1.0 × (2020-06-01 分红 change = (100-5)/100 = 0.95)
    assert by_date["2018-01-15"] == 0.95
    # 2016-03-01 = 0.95 × 合并 change(分红 (10-2)/10=0.8 × 合股 10.0 = 8.0)= 7.6
    # 证明是连乘合并(若取 max/min 等去重则不会得到 7.6);
    # 合并 change=8.0 与 raw 跳空 10.0 在容差内,审计判定为真实事件 → 保留
    assert by_date["2016-03-01"] == round(0.95 * 8.0, 6)


def test_nan_dividend_amount_skipped():
    """yfinance 返回 NaN 分红额时应跳过,不得产出 None/NaN 因子。"""
    hist = pd.DataFrame(
        {"Close": [100.0, 100.0, 100.0, 100.0]},
        index=pd.to_datetime(
            ["2020-05-29", "2020-06-01", "2022-05-19", "2022-05-20"]
        ),
    )
    # 2020-06-01 分红额为 NaN(脏数据),2022-05-20 正常 amount=10 → 0.90
    divs = pd.Series(
        [float("nan"), 10.0],
        index=pd.to_datetime(["2020-06-01", "2022-05-20"]),
    )
    splits = pd.Series([], index=pd.to_datetime([]), dtype=float)

    records = _run(hist, divs, splits)

    # NaN 事件被跳过 → 只剩 2022-05-20 一个有效事件(最新,锚定 1.0)
    assert all(r.foreAdjustFactor is not None for r in records)
    assert [r.dividOperateDate for r in records] == ["2022-05-20"]
    assert records[0].foreAdjustFactor == 1.0
