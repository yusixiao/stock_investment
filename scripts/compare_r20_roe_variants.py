"""R20 配方 × 3 个 ROE 处理方案对比

目的:验证 5 月调仓 ROEJQ 单季度过严的影响,在 R20 (PB≤1 + ROE + 动量 + top15)
基础上,只换 ROE 过滤的处理方式,跑 2010-05-01 ~ 2025-12-31 全期回测,
对比 CAGR / DD / Sharpe。

3 个变体:
  V0 (baseline)  : 现行 R20,所有报告期统一 ROEJQ > 5%(实际 5 月 Q1 报告几乎全刷掉)
  V1 (smart)     : 按报告期智能阈值
                     Q1 报告(REPORT_DATE 月份 03)→ 阈值 × 1/4 = 1.25%
                     H1   (06) → × 1/2 = 2.5%
                     Q3   (09) → × 3/4 = 3.75%
                     年报 (12) → × 1   = 5%
  V2 (annual_only): 永远只用最近一个年报(REPORT_DATE 以 -12-31 结尾)的 ROEJQ,
                     阈值固定 5%。语义最干净,但可能延迟新股加入。

注:本脚本复用 backtest_low_pb_value.py 的 panel 构造/回测引擎,只替换 ROE 过滤函数。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

# 复用 backtest_low_pb_value 模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.backtest_low_pb_value import (  # noqa: E402
    SelectFn,
    SelectionContext,
    equal_weight,
    gen_rebalance_dates,
    load_pe_pb_panel,
    load_qfq_close_panel,
    load_roe_panel,
    metrics,
    run_backtest,
)
from services.market_data.duckdb_store import init_duckdb  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("r20_roe_variants")


# ---------- ROE 查找函数(3 个变体) ----------


def build_roe_lookup_v0(roe_panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """V0 baseline:与 backtest_low_pb_value.build_roe_lookup 相同。
    每行直接给 ROEJQ,无视 REPORT_DATE 月份。
    """
    g = roe_panel.sort_values(["code", "NOTICE_DATE", "REPORT_DATE"]).drop_duplicates(
        ["code", "NOTICE_DATE"], keep="last"
    )
    out = {}
    for code, sub in g.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def build_roe_lookup_v1(roe_panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """V1 smart:在 lookup 上多挂一列 'roe_norm' = ROEJQ × 期数倍率,
    使得阈值统一为 5%(年化口径)。

    倍率 = 4 / 季度数:Q1 ×4, H1 ×2, Q3 ×4/3, 年报 ×1。
    这样下游过滤 'roe_norm > 5' 等价于 V1 智能阈值。
    """
    g = (
        roe_panel.sort_values(["code", "NOTICE_DATE", "REPORT_DATE"])
        .drop_duplicates(["code", "NOTICE_DATE"], keep="last")
        .copy()
    )
    # 解析 REPORT_DATE 月份
    rep_month = pd.to_datetime(g["REPORT_DATE"]).dt.month
    # 月份 → 倍率(累计期为 1/2/3/4 季度)
    factor = rep_month.map({3: 4.0, 6: 2.0, 9: 4.0 / 3.0, 12: 1.0})
    g["roe_norm"] = g["ROEJQ"] * factor
    out = {}
    for code, sub in g.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def build_roe_lookup_v2(roe_panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """V2 annual_only:只保留 REPORT_DATE 月份=12 的年报。"""
    annual = roe_panel[pd.to_datetime(roe_panel["REPORT_DATE"]).dt.month == 12].copy()
    g = annual.sort_values(["code", "NOTICE_DATE", "REPORT_DATE"]).drop_duplicates(
        ["code", "NOTICE_DATE"], keep="last"
    )
    out = {}
    for code, sub in g.groupby("code"):
        out[code] = sub.sort_values("NOTICE_DATE").reset_index(drop=True)
    return out


def make_roe_getter(lookup: dict[str, pd.DataFrame], col: str = "ROEJQ"):
    """返回一个 (code, date) → float|None 的查询函数,col 指定值列。"""

    def get(code: str, date: str):
        g = lookup.get(code)
        if g is None or g.empty:
            return None
        idx = g["NOTICE_DATE"].searchsorted(date, side="right") - 1
        if idx < 0:
            return None
        v = g.iloc[idx][col]
        if pd.isna(v):
            return None
        return float(v)

    return get


# ---------- R20 选股函数(参数化 ROE 取值) ----------


def make_r20_select(
    roe_get,
    qfq_close: pd.DataFrame,
    roe_min: float = 0.05,
    mom_lookback_days: int = 120,
    drop_pct: float = 0.2,
    top_n: int = 15,
) -> SelectFn:
    """R20 配方,ROE 取值器外注入。"""
    dates_arr = qfq_close.index

    def fn(ctx: SelectionContext) -> list[str]:
        pool = ctx.panel[
            (ctx.panel["pbMRQ"] < 1)
            & (ctx.panel["pbMRQ"] > 0)
            & (ctx.panel["isST"].astype(str) == "0")
            & (ctx.panel["peTTM"] > 0)
        ].copy()
        roe_vals = pool["code"].apply(lambda c: roe_get(c, ctx.date))
        pool["roe"] = roe_vals
        pool = pool[pool["roe"].notna() & (pool["roe"] > roe_min * 100)]
        if ctx.date in qfq_close.index:
            i = dates_arr.get_loc(ctx.date)
            j = max(0, i - mom_lookback_days)
            past = qfq_close.iloc[j]
            now = qfq_close.iloc[i]
            mom = now / past - 1
            pool["mom"] = pool["code"].map(mom.to_dict())
            pool = pool.dropna(subset=["mom"])
            cutoff = pool["mom"].quantile(drop_pct)
            pool = pool[pool["mom"] >= cutoff]
        pool = pool.sort_values("pbMRQ")
        return pool.head(top_n)["code"].tolist()

    return fn


def main():
    init_duckdb()
    START = "2010-05-01"
    END = "2025-12-31"

    logger.info(f"载入估值面板 {START} ~ {END} ...")
    val_panel = load_pe_pb_panel(START, END)
    logger.info(f"载入 qfq 收盘价面板 ...")
    qfq = load_qfq_close_panel(START, END)
    logger.info(f"载入 ROE 披露面板 ...")
    roe_panel = load_roe_panel(START, END)

    # 调仓日 = 每年 5/9/11 月首交易日(R20 季度调仓口径)
    rebal_dates = gen_rebalance_dates(qfq.index, [(5, 1), (9, 1), (11, 1)])
    logger.info(f"调仓 {len(rebal_dates)} 次")

    # 3 变体的 lookup + getter
    lk_v0 = build_roe_lookup_v0(roe_panel)
    lk_v1 = build_roe_lookup_v1(roe_panel)
    lk_v2 = build_roe_lookup_v2(roe_panel)

    get_v0 = make_roe_getter(lk_v0, col="ROEJQ")
    get_v1 = make_roe_getter(lk_v1, col="roe_norm")
    get_v2 = make_roe_getter(lk_v2, col="ROEJQ")

    rounds = [
        ("V0 baseline R20 (统一 ROE>5%)", get_v0),
        ("V1 smart 期数归一化 (annualized > 5%)", get_v1),
        ("V2 annual_only (仅年报 ROE > 5%)", get_v2),
    ]

    summary = []
    for name, getter in rounds:
        logger.info(f"\n==================== {name} ====================")
        sel = make_r20_select(
            getter, qfq, roe_min=0.05, mom_lookback_days=120, drop_pct=0.2, top_n=15
        )
        res = run_backtest(val_panel, qfq, rebal_dates, sel, weight_fn=equal_weight)
        m = metrics(res.equity)
        logger.info(
            f"{name}: CAGR={m['CAGR']:.2%}  total={m['total_return']:.1%}  "
            f"max_dd={m['max_drawdown']:.1%}  vol={m['ann_vol']:.1%}  sharpe={m['sharpe']:.2f}  "
            f"rebals={len(res.trades_log)}"
        )
        summary.append(
            {
                "variant": name,
                "CAGR": m["CAGR"],
                "total": m["total_return"],
                "max_dd": m["max_drawdown"],
                "vol": m["ann_vol"],
                "sharpe": m["sharpe"],
                "years": m["years"],
            }
        )

    print("\n========== 对比汇总 ==========")
    df = pd.DataFrame(summary)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
