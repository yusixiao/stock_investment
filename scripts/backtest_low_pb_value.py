"""低 PB 价值策略回测 — 跨股票 cross-sectional 组合调仓,2010-2025 全 A 股。

设计:
- 数据源:`v_a_daily`(pbMRQ / peTTM / isST,T 日数据 T 日收盘后已知,无 look-ahead)
- 收益:`query_qfq_kline_bulk('A')` 全市场 qfq 收盘价,日级单股票收益按 qfq close 派生
- 调仓:在指定日期按 selection_fn 选股、weighting_fn 给权重,日终重置;
        调仓日 D 选股逻辑只用 D 当日(含)及之前数据,避免 look-ahead
- 持有期收益:从 D+1 日开始按权重 × 单股票日收益累加(D 当日按收盘价开仓所以
        D 当日不计入组合收益;next_rebal D' 日按 D' 收盘价重平衡)
- 交易成本:换手率 × 单边费率(默认 0.1%/单边)
- 空仓:候选不足 min_hold 时空仓,资金不滚息(保守口径)
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, "backend")
from services.duckdb_store import init_duckdb, get_store  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


# ---------- 1) 数据加载 ----------


def load_pe_pb_panel(start: str, end: str) -> pd.DataFrame:
    """全 A 股 daily 估值面板:date / code / pbMRQ / peTTM / isST。

    单笔 SQL 拉全期(2010-2025 ~700 万行,DuckDB 列存,~5s)。
    """
    s = get_store()
    sql = f"""
        SELECT date, _symbol AS code, pbMRQ, peTTM, isST, close
        FROM v_a_daily
        WHERE date BETWEEN '{start}' AND '{end}'
          AND pbMRQ IS NOT NULL
    """
    df = s._conn.execute(sql).fetchdf()
    df["date"] = df["date"].astype(str)
    return df


def load_roe_panel(start: str, end: str) -> pd.DataFrame:
    """ROE 披露面板:code / NOTICE_DATE / REPORT_DATE / ROEJQ。

    用 NOTICE_DATE(披露公告日)做 look-ahead 防护:
    选股日 D 只能使用 NOTICE_DATE <= D 的报告。
    返回 long-format,使用方按 code+date 二分查找最新值。
    """
    s = get_store()
    sql = f"""
        SELECT _symbol AS code,
               NOTICE_DATE,
               REPORT_DATE,
               ROEJQ
        FROM v_a_indicator
        WHERE NOTICE_DATE IS NOT NULL
          AND NOTICE_DATE BETWEEN '2009-01-01' AND '{end}'
          AND ROEJQ IS NOT NULL
        ORDER BY code, NOTICE_DATE
    """
    df = s._conn.execute(sql).fetchdf()
    df["NOTICE_DATE"] = df["NOTICE_DATE"].astype(str)
    df["REPORT_DATE"] = df["REPORT_DATE"].astype(str)
    return df


def build_roe_lookup(roe_panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """按 code 分组,用于 (code, date) 快速查最新已披露 ROE。

    去重铁律:相同 (code, NOTICE_DATE) 可能有多条(IPO 招股书 / 重述报告),
    用最大 REPORT_DATE 作为 tiebreak(最近期的 fiscal period 为准),
    保证查询结果**确定性**。
    """
    # 同 (code, NOTICE_DATE) 取最大 REPORT_DATE 的一行
    g = roe_panel.sort_values(["code", "NOTICE_DATE", "REPORT_DATE"]).drop_duplicates(
        ["code", "NOTICE_DATE"], keep="last"
    )
    out = {}
    for code, sub in g.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def get_roe_as_of(
    lookup: dict[str, pd.DataFrame], code: str, date: str
) -> Optional[float]:
    """二分查找:返回 NOTICE_DATE <= date 的最新 ROEJQ。"""
    g = lookup.get(code)
    if g is None or g.empty:
        return None
    # NOTICE_DATE 已排序 → searchsorted
    idx = g["NOTICE_DATE"].searchsorted(date, side="right") - 1
    if idx < 0:
        return None
    return float(g.iloc[idx]["ROEJQ"])


def load_qfq_close_panel(start: str, end: str) -> pd.DataFrame:
    """全 A 股 qfq 日收盘价宽表:index=date(str), columns=code, values=close。

    用 query_qfq_kline_bulk 取 A 股全市场,长格式 → pivot 成宽表。
    """
    s = get_store()
    bulk = s.query_qfq_kline_bulk("A", symbols=None, start=start, end=end)
    parts = []
    for code, df in bulk.items():
        if df is None or df.empty:
            continue
        sub = df[["date", "close"]].copy()
        sub["code"] = code
        parts.append(sub)
    long = pd.concat(parts, ignore_index=True)
    long["date"] = long["date"].astype(str)
    wide = long.pivot(index="date", columns="code", values="close").sort_index()
    return wide


# ---------- 2) 调仓日生成 ----------


def gen_rebalance_dates(
    trading_dates: pd.Index, months_days: list[tuple[int, int]]
) -> list[str]:
    """在每年的 (month, day) 列表里,取交易日中 >= 该日的第一个交易日。

    months_days 例:[(5, 1)] → 每年 5/1 后首个交易日(年度);
                  [(5, 1), (9, 1)] → 每年 5/1 + 9/1(半年);
    """
    out: list[str] = []
    td = pd.to_datetime(trading_dates)
    by_year: dict[int, list[pd.Timestamp]] = {}
    for d in td:
        by_year.setdefault(d.year, []).append(d)
    for year, days in sorted(by_year.items()):
        for month, day in months_days:
            target = pd.Timestamp(year=year, month=month, day=day)
            cand = [d for d in days if d >= target]
            if cand:
                out.append(cand[0].strftime("%Y-%m-%d"))
    return sorted(set(out))


# ---------- 3) 选股 / 加权策略接口 ----------


@dataclass
class SelectionContext:
    date: str
    panel: pd.DataFrame  # 当日估值切片 (code/pbMRQ/peTTM/isST/close)
    history: pd.DataFrame  # date <= 当日 的全历史(若策略需要)


SelectFn = Callable[[SelectionContext], list[str]]
WeightFn = Callable[[list[str], SelectionContext], dict[str, float]]


def equal_weight(symbols: list[str], _: SelectionContext) -> dict[str, float]:
    if not symbols:
        return {}
    w = 1.0 / len(symbols)
    return {s: w for s in symbols}


def inv_pb_weight(symbols: list[str], ctx: SelectionContext) -> dict[str, float]:
    """1/PB 加权,PB 越低权重越大。"""
    if not symbols:
        return {}
    sub = ctx.panel.set_index("code").loc[symbols]
    inv = 1.0 / sub["pbMRQ"].clip(lower=1e-3)
    w = inv / inv.sum()
    return w.to_dict()


# ---------- 4) 回测主循环 ----------


@dataclass
class BacktestResult:
    equity: pd.Series  # 日级权益(初始 1.0 normalized)
    trades_log: pd.DataFrame  # 调仓日记录
    holdings_log: pd.DataFrame  # 调仓日持仓


def run_backtest(
    valuation_panel: pd.DataFrame,
    qfq_close: pd.DataFrame,
    rebalance_dates: list[str],
    select_fn: SelectFn,
    weight_fn: WeightFn = equal_weight,
    cost_per_side: float = 0.001,  # 单边 0.1%
    min_hold: int = 5,
) -> BacktestResult:
    trading_dates = list(qfq_close.index)
    daily_ret = qfq_close.pct_change()  # 单股票日收益

    equity = 1.0
    weights: dict[str, float] = {}  # 当前持仓权重(对组合权益的占比)
    equity_series = []
    trades = []
    holdings = []

    panel_by_date = {d: g for d, g in valuation_panel.groupby("date")}

    for i, today in enumerate(trading_dates):
        # 调仓日:在收盘后用今日数据选股,生成新权重
        if today in set(rebalance_dates):
            today_panel = panel_by_date.get(today)
            if today_panel is not None and not today_panel.empty:
                hist = valuation_panel[valuation_panel["date"] <= today]
                ctx = SelectionContext(date=today, panel=today_panel, history=hist)
                selected = select_fn(ctx)
                # 限制只在 qfq_close 也有数据的股票里(否则后面 reindex 找不到)
                selected = [s for s in selected if s in qfq_close.columns]
                if len(selected) >= min_hold:
                    new_weights = weight_fn(selected, ctx)
                    # 换手 = Σ |w_new - w_old|(双边),近似单边交易成本
                    all_codes = set(weights) | set(new_weights)
                    turnover = sum(
                        abs(new_weights.get(c, 0) - weights.get(c, 0))
                        for c in all_codes
                    )
                    cost = turnover * cost_per_side  # 单边
                    equity *= 1.0 - cost
                    weights = new_weights
                else:
                    # 候选不足 → 清仓空仓
                    if weights:
                        equity *= 1.0 - sum(weights.values()) * cost_per_side
                        weights = {}
                trades.append(
                    {
                        "date": today,
                        "n_holdings": len(weights),
                        "turnover": turnover if weights else 0,
                    }
                )
                holdings.append({"date": today, "codes": list(weights.keys())})

        # 持有期:从 D+1 起,today 不计入组合收益(权重于 today 收盘建仓)
        if i + 1 < len(trading_dates) and weights:
            tomorrow = trading_dates[i + 1]
            if tomorrow in daily_ret.index:
                rets = daily_ret.loc[tomorrow]
                # weights dict → align
                w_arr = pd.Series(weights)
                aligned = rets.reindex(w_arr.index).fillna(0)  # 停牌等缺失视为 0
                port_ret = float((aligned * w_arr).sum())
                equity *= 1.0 + port_ret
                # 漂移更新权重(下一调仓日重置)
                grow = (1 + aligned) * w_arr
                w_arr = grow / grow.sum()
                weights = w_arr.to_dict()

        equity_series.append((today, equity))

    eq = pd.Series([v for _, v in equity_series], index=[d for d, _ in equity_series])
    return BacktestResult(
        equity=eq,
        trades_log=pd.DataFrame(trades),
        holdings_log=pd.DataFrame(holdings),
    )


# ---------- 5) 指标 ----------


def metrics(eq: pd.Series) -> dict:
    if eq.empty:
        return {}
    eq = eq.dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    days = (pd.to_datetime(eq.index[-1]) - pd.to_datetime(eq.index[0])).days
    years = max(days / 365.25, 1e-9)
    cagr = (1 + total) ** (1 / years) - 1
    # 最大回撤
    roll_max = eq.cummax()
    dd = (eq / roll_max - 1).min()
    # 年化波动(日频 → ×√252)
    rets = eq.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = (rets.mean() * 252) / (rets.std() * np.sqrt(252) + 1e-9)
    return {
        "total_return": total,
        "CAGR": cagr,
        "max_drawdown": dd,
        "ann_vol": vol,
        "sharpe": sharpe,
        "years": years,
    }


# ---------- 6) 选股策略实现 ----------


def select_pure_pb_under_1(top_n: int = 30) -> SelectFn:
    """R1: 纯 PB<1,取 PB 最低的 top_n 只(避免池子过大稀释)。"""

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel.query("pbMRQ < 1 and pbMRQ > 0").sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def select_pb_under_1_quality(top_n: int = 30) -> SelectFn:
    """R2: PB<1 + 排 ST + 排 peTTM<=0 (亏损)。"""

    def fn(ctx: SelectionContext) -> list[str]:
        # isST 是 VARCHAR '0'/'1';peTTM 可能为 NaN
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] < 1)
            & (ctx.panel["pbMRQ"] > 0)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ].sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def select_pb_under_1_no_finance(top_n: int = 30) -> SelectFn:
    """R5: R2 + 排金融股(银行 / 保险 / 证券 — 通过股票代码段近似)。

    A 股银行多在 6011xx / 6019xx / 0019xx,保险 6013xx,证券 6005xx / 0007xx;
    粗筛用代码段不够精准但成本低,目标只是看金融股是否污染结果。
    """
    finance_prefixes = ("6011", "6019", "6013", "6005", "0019", "0007", "6018")

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] < 1)
            & (ctx.panel["pbMRQ"] > 0)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ]
        codes = pool["code"].astype(str)
        # code 形如 "000001.SZ",前 4 位数判金融段
        prefix = codes.str.split(".").str[0].str[:4]
        mask = ~prefix.isin(finance_prefixes)
        pool = pool[mask].sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def select_pb_quality_roe(
    roe_lookup: dict[str, pd.DataFrame],
    roe_min: float = 0.05,
    top_n: int = 30,
) -> SelectFn:
    """R6: R2 + ROE > roe_min(用 NOTICE_DATE <= D 的最新报告,无 look-ahead)。

    ROEJQ 单位是百分比(eg 9.15 表示 9.15%),所以 roe_min=5 对应 5%。
    """

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] < 1)
            & (ctx.panel["pbMRQ"] > 0)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ].copy()
        # 附加 ROE(N×lookup)
        roe_vals = pool["code"].apply(lambda c: get_roe_as_of(roe_lookup, c, ctx.date))
        pool["roe"] = roe_vals
        pool = pool[pool["roe"].notna() & (pool["roe"] > roe_min * 100)]
        pool = pool.sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def select_pb_roe_momentum(
    roe_lookup: dict[str, pd.DataFrame],
    qfq_close: pd.DataFrame,
    roe_min: float = 0.05,
    mom_lookback_days: int = 120,  # ~6m
    drop_pct: float = 0.2,  # 剔除动量最差 20%
    top_n: int = 30,
) -> SelectFn:
    """R16+: PB<1 + ROE>min + 排动量最差 drop_pct(避免下跌中接刀)。

    动量 = 当日 close / lookback_days 前 close - 1,用 qfq close 算。
    """
    dates_arr = qfq_close.index

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] < 1)
            & (ctx.panel["pbMRQ"] > 0)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ].copy()
        roe_vals = pool["code"].apply(lambda c: get_roe_as_of(roe_lookup, c, ctx.date))
        pool["roe"] = roe_vals
        pool = pool[pool["roe"].notna() & (pool["roe"] > roe_min * 100)]
        # 动量
        if ctx.date in qfq_close.index:
            i = dates_arr.get_loc(ctx.date)
            j = max(0, i - mom_lookback_days)
            past = qfq_close.iloc[j]
            now = qfq_close.iloc[i]
            mom = now / past - 1
            pool["mom"] = pool["code"].map(mom.to_dict())
            pool = pool.dropna(subset=["mom"])
            # 剔除动量最差 drop_pct
            cutoff = pool["mom"].quantile(drop_pct)
            pool = pool[pool["mom"] >= cutoff]
        pool = pool.sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def select_pb_range_roe(
    roe_lookup: dict[str, pd.DataFrame],
    pb_low: float = 0.3,
    pb_high: float = 1.0,
    roe_min: float = 0.05,
    top_n: int = 30,
) -> SelectFn:
    """R12/R13: PB ∈ (pb_low, pb_high) + ROE>roe_min。"""

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] >= pb_low)
            & (ctx.panel["pbMRQ"] < pb_high)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ].copy()
        roe_vals = pool["code"].apply(lambda c: get_roe_as_of(roe_lookup, c, ctx.date))
        pool["roe"] = roe_vals
        pool = pool[pool["roe"].notna() & (pool["roe"] > roe_min * 100)]
        pool = pool.sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def select_pb_range_quality(
    pb_low: float = 0.3, pb_high: float = 1.0, top_n: int = 30
) -> SelectFn:
    """R7: PB ∈ (pb_low, pb_high) + 排 ST/亏损,排极廉股(可能退市/重组瑕疵)。"""

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] >= pb_low)
            & (ctx.panel["pbMRQ"] < pb_high)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ].sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


# ---------- 7) 主入口:逐轮跑 ----------


def main():
    init_duckdb()
    START = "2010-05-01"
    END = "2025-12-31"

    logger.info(f"载入估值面板 {START} ~ {END} ...")
    val_panel = load_pe_pb_panel(START, END)
    logger.info(f"估值面板 rows={len(val_panel)}")
    logger.info(f"载入 qfq 收盘价面板 ...")
    qfq = load_qfq_close_panel(START, END)
    logger.info(f"qfq panel shape={qfq.shape}")

    annual_dates = gen_rebalance_dates(qfq.index, [(5, 1)])
    semi_dates = gen_rebalance_dates(qfq.index, [(5, 1), (9, 1)])
    quarterly_dates = gen_rebalance_dates(qfq.index, [(5, 1), (9, 1), (11, 1)])
    logger.info(
        f"年度调仓 {len(annual_dates)} 次, 半年度 {len(semi_dates)} 次, "
        f"季度(三次) {len(quarterly_dates)} 次"
    )

    logger.info(f"载入 ROE 披露面板 ...")
    roe_panel = load_roe_panel(START, END)
    logger.info(f"ROE 披露面板 rows={len(roe_panel)}")
    roe_lookup = build_roe_lookup(roe_panel)
    logger.info(f"ROE lookup codes={len(roe_lookup)}")

    rounds = [
        (
            "R1 纯 PB<1 等权 年度",
            select_pure_pb_under_1(30),
            equal_weight,
            annual_dates,
        ),
        (
            "R2 + 排 ST/亏损 等权 年度",
            select_pb_under_1_quality(30),
            equal_weight,
            annual_dates,
        ),
        (
            "R3 + 半年调仓",
            select_pb_under_1_quality(30),
            equal_weight,
            semi_dates,
        ),
        (
            "R4 + 1/PB 加权 (半年)",
            select_pb_under_1_quality(30),
            inv_pb_weight,
            semi_dates,
        ),
        (
            "R5 + 排金融 等权 半年",
            select_pb_under_1_no_finance(30),
            equal_weight,
            semi_dates,
        ),
        (
            "R6 R3 + ROE>5% 等权 半年",
            select_pb_quality_roe(roe_lookup, roe_min=0.05, top_n=30),
            equal_weight,
            semi_dates,
        ),
        (
            "R7 PB∈(0.3,1) 等权 半年",
            select_pb_range_quality(0.3, 1.0, 30),
            equal_weight,
            semi_dates,
        ),
        (
            "R8 R3 三次/年(5/9/11)",
            select_pb_under_1_quality(30),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R9 R3 + ROE>8% + 三次/年",
            select_pb_quality_roe(roe_lookup, roe_min=0.08, top_n=30),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R10 R3 + ROE>10% top20 三次/年",
            select_pb_quality_roe(roe_lookup, roe_min=0.10, top_n=20),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R11 R6 + 三次/年(ROE>5%)",
            select_pb_quality_roe(roe_lookup, roe_min=0.05, top_n=30),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R12 PB∈(0.3,1) + ROE>5% 半年",
            select_pb_range_roe(roe_lookup, 0.3, 1.0, 0.05, 30),
            equal_weight,
            semi_dates,
        ),
        (
            "R13 PB∈(0.3,1) + ROE>5% 三次/年",
            select_pb_range_roe(roe_lookup, 0.3, 1.0, 0.05, 30),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R14 R6 ROE>6% top40 半年",
            select_pb_quality_roe(roe_lookup, roe_min=0.06, top_n=40),
            equal_weight,
            semi_dates,
        ),
        (
            "R15 R6 ROE>5% top50 半年",
            select_pb_quality_roe(roe_lookup, roe_min=0.05, top_n=50),
            equal_weight,
            semi_dates,
        ),
        (
            "R16 R11 top20 集中",
            select_pb_quality_roe(roe_lookup, roe_min=0.05, top_n=20),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R17 R11 + 排动量最差20% (6m)",
            select_pb_roe_momentum(
                roe_lookup,
                qfq,
                roe_min=0.05,
                mom_lookback_days=120,
                drop_pct=0.2,
                top_n=30,
            ),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R18 R11 + 排动量最差30% (6m)",
            select_pb_roe_momentum(
                roe_lookup,
                qfq,
                roe_min=0.05,
                mom_lookback_days=120,
                drop_pct=0.3,
                top_n=30,
            ),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R19 R11 + 排动量最差20% (12m)",
            select_pb_roe_momentum(
                roe_lookup,
                qfq,
                roe_min=0.05,
                mom_lookback_days=240,
                drop_pct=0.2,
                top_n=30,
            ),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R20 R11 top15 + 排动量最差20% (6m)",
            select_pb_roe_momentum(
                roe_lookup,
                qfq,
                roe_min=0.05,
                mom_lookback_days=120,
                drop_pct=0.2,
                top_n=15,
            ),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R21 R16 top10 极致集中",
            select_pb_quality_roe(roe_lookup, roe_min=0.05, top_n=10),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R22 R16 top25",
            select_pb_quality_roe(roe_lookup, roe_min=0.05, top_n=25),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R23 R16 + 排动量最差20%",
            select_pb_roe_momentum(
                roe_lookup,
                qfq,
                roe_min=0.05,
                mom_lookback_days=120,
                drop_pct=0.2,
                top_n=20,
            ),
            equal_weight,
            quarterly_dates,
        ),
        (
            "R24 R16 ROE>3% top20",
            select_pb_quality_roe(roe_lookup, roe_min=0.03, top_n=20),
            equal_weight,
            quarterly_dates,
        ),
    ]

    summary = []
    eq_by_round = {}
    for name, sel, wfn, rebal in rounds:
        logger.info(f"\n==================== {name} ====================")
        res = run_backtest(val_panel, qfq, rebal, sel, weight_fn=wfn)
        m = metrics(res.equity)
        logger.info(
            f"{name}: CAGR={m['CAGR']:.2%}  total={m['total_return']:.1%}  "
            f"max_dd={m['max_drawdown']:.1%}  vol={m['ann_vol']:.1%}  sharpe={m['sharpe']:.2f}"
        )
        summary.append(
            {
                "round": name,
                "CAGR": m["CAGR"],
                "total": m["total_return"],
                "max_dd": m["max_drawdown"],
                "vol": m["ann_vol"],
                "sharpe": m["sharpe"],
                "years": m["years"],
            }
        )
        eq_by_round[name] = res.equity
        # 简要打印调仓时点的持仓数量
        if not res.trades_log.empty:
            logger.info(
                f"  调仓 N 分布: min={res.trades_log['n_holdings'].min()} "
                f"med={res.trades_log['n_holdings'].median():.0f} "
                f"max={res.trades_log['n_holdings'].max()}"
            )

    # 汇总
    print("\n\n========== 汇总 ==========")
    df = pd.DataFrame(summary)
    df["CAGR"] = df["CAGR"].apply(lambda x: f"{x:.2%}")
    df["total"] = df["total"].apply(lambda x: f"{x:.1%}")
    df["max_dd"] = df["max_dd"].apply(lambda x: f"{x:.1%}")
    df["vol"] = df["vol"].apply(lambda x: f"{x:.1%}")
    df["sharpe"] = df["sharpe"].apply(lambda x: f"{x:.2f}")
    df["years"] = df["years"].apply(lambda x: f"{x:.1f}")
    print(df.to_string(index=False))

    # 保存权益曲线
    eq_df = pd.DataFrame(eq_by_round)
    eq_df.to_csv("/tmp/low_pb_equity_curves.csv")
    print("\n权益曲线 → /tmp/low_pb_equity_curves.csv")


if __name__ == "__main__":
    main()
