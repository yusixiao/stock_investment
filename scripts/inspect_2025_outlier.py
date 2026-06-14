"""核查 R20 的 2025 离群值(+262%)—— 把 2025 年净值增长按个股归因。

方法:重跑 BASE_G25 连续回测,从 equity_curve 的每日持仓快照做**逐日
mark-to-market 归因**:每个交易日 contribution_sym += prev_shares × (今收 - 昨收),
全年累加 = 该股 2025 对组合的 HKD 贡献。自然处理 6 月调仓换股。

再对 top 贡献股附上:2025 年个股涨幅(首→末收盘)+ 2025 日均成交额(HKD,查流动性),
判断 +262% 是否被一两只小盘/低流动性暴涨票绑架。

输出:exported/inspect_2025_outlier.md
用法:python scripts/bg_launch.py logs/inspect_2025.log python scripts/inspect_2025_outlier.py
"""

import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("inspect2025")

import pandas as pd
from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import growth_hk, hk_industry
from services.backtest.strategies.deployed.hk_garp_strategy import HkGarpStrategy

START = "2010-01-01"
END = "2026-06-01"
YEAR = "2025"
OUT_DIR = ROOT / "report" / "exported"

BASE_G25 = {
    "top_n": 12, "min_amount_hkd": 1e7, "rebalance_months": [6],
    "cagr_years": 5, "trend_ma_days": 90, "require_industry": True,
    "max_per_sector": 2, "np_cagr_min": 0.25,
}


def _pct(x):
    return "-" if x is None else f"{x * 100:+.2f}%"


def _stock_year_stats(sliced, sym, year):
    """个股某年:首末收盘价涨幅 + 日均成交额(HKD)。"""
    df = sliced.stock_data.get(sym)
    if df is None or df.empty:
        return None, None, None
    d = df[df["date"].astype(str).str.startswith(year)]
    if d.empty:
        return None, None, None
    first_c = float(d.iloc[0]["close"])
    last_c = float(d.iloc[-1]["close"])
    ret = last_c / first_c - 1 if first_c > 0 else None
    if "amount" in d.columns:
        turnover = float(d["amount"].mean())
    else:
        turnover = float((d["volume"] * d["close"]).mean())
    return ret, turnover, len(d)


def main():
    growth_hk.reset_cache()
    hk_industry.reset_cache()
    log.info("加载 HK bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, START, END)

    strat = HkGarpStrategy(param_overrides=BASE_G25)
    engine = BacktestEngine(
        strategy=strat, stock_data=sliced.stock_data,
        valuation_data=sliced.valuation_data, dividend_data=sliced.dividend_data,
        financial_data=sliced.financial_data, balance_data=sliced.balance_data,
        cashflow_data=sliced.cashflow_data, income_data=sliced.income_data,
        weekly_data=sliced.weekly_data, monthly_data=sliced.monthly_data,
        iter_start=sliced.iter_start_idx, iter_end=sliced.iter_end_idx,
        enable_decision_log=False,
    )
    log.info("running BASE_G25 continuous ...")
    t1 = time.time()
    result = engine.run()
    log.info("backtest done in %.1fs", time.time() - t1)
    eq = result["equity_curve"]

    # ---- 找 2025 起止净值 ----
    val_2024_end = None
    val_2025_end = None
    for pt in eq:
        y = pt["date"][:4]
        if y == "2024":
            val_2024_end = float(pt["value"])
        elif y == YEAR:
            val_2025_end = float(pt["value"])
    gain_2025 = (val_2025_end - val_2024_end) if (val_2024_end and val_2025_end) else None
    log.info("2025 起 %.0f → 末 %.0f, 增长 %.0f (%s)",
             val_2024_end or 0, val_2025_end or 0, gain_2025 or 0,
             _pct(val_2025_end / val_2024_end - 1) if val_2024_end else "?")

    # ---- 逐日 mark-to-market 归因(仅 2025 交易日)----
    # contribution_sym = Σ prev_shares × (cur_price - prev_price)
    contrib = defaultdict(float)
    prev_pos = None  # {sym: (shares, market_price)}
    prev_year = None
    for pt in eq:
        cur_year = pt["date"][:4]
        cur_pos = {s: (p["shares"], p["market_price"])
                   for s, p in pt["positions"].items()}
        # 只在 2025 区间内累加(prev 是 2024 末或 2025 内)
        if prev_pos is not None and cur_year == YEAR:
            for sym, (sh, _cur_price) in cur_pos.items():
                if sym in prev_pos:
                    p_sh, p_price = prev_pos[sym]
                    contrib[sym] += p_sh * (_cur_price - p_price)
        prev_pos = cur_pos
        prev_year = cur_year

    ranked = sorted(contrib.items(), key=lambda kv: kv[1], reverse=True)

    # ---- 组装报告 ----
    lines = [
        "# 2025 离群值核查 —— BASE_G25 年度净值增长个股归因",
        "",
        f"2025 起始净值 {val_2024_end:,.0f} → 末 {val_2025_end:,.0f} | "
        f"年度增长 {gain_2025:,.0f} HKD ({_pct(val_2025_end / val_2024_end - 1)})",
        "",
        "> 归因 = 逐日 mark-to-market(prev_shares × 当日价格变动)累加;"
        "占比 = 个股贡献 / 当年净值增长额。",
        "> 个股涨幅 = 该股 2025 首→末收盘;日均成交额 = 2025 日均 amount(HKD),判流动性。",
        "",
        "| 排名 | 代码 | 贡献(HKD) | 占当年增长 | 该股2025涨幅 | 2025日均成交额 | 交易日 |",
        "|---|---|---|---|---|---|---|",
    ]
    cum_share = 0.0
    top_rows = ranked[:20]
    for i, (sym, c) in enumerate(top_rows, 1):
        share = c / gain_2025 if gain_2025 else None
        cum_share += (share or 0)
        ret, turnover, ndays = _stock_year_stats(sliced, sym, YEAR)
        turn_str = "-" if turnover is None else f"{turnover / 1e6:,.1f}M"
        lines.append(
            f"| {i} | {sym} | {c:,.0f} | {_pct(share)} | "
            f"{_pct(ret)} | {turn_str} | {ndays if ndays else '-'} |"
        )

    # 集中度统计
    total_pos = sum(c for _, c in ranked if c > 0)
    top1 = ranked[0][1] if ranked else 0
    top3 = sum(c for _, c in ranked[:3])
    top5 = sum(c for _, c in ranked[:5])
    lines += [
        "",
        "## 集中度",
        "",
        f"- 全年净值增长额:{gain_2025:,.0f} HKD",
        f"- Top1 贡献:{top1:,.0f} = 当年增长的 {_pct(top1 / gain_2025) if gain_2025 else '-'}",
        f"- Top3 贡献:{top3:,.0f} = {_pct(top3 / gain_2025) if gain_2025 else '-'}",
        f"- Top5 贡献:{top5:,.0f} = {_pct(top5 / gain_2025) if gain_2025 else '-'}",
        f"- Top20 累计占比:{_pct(cum_share)}",
        f"- 2025 期间持有过的股票数:{len(contrib)}",
    ]
    out = OUT_DIR / "inspect_2025_outlier.md"
    out.write_text("\n".join(lines))
    log.info("DONE -> %s", out)
    # 控制台也打印 top10 便于日志直读
    for i, (sym, c) in enumerate(ranked[:10], 1):
        ret, turnover, _ = _stock_year_stats(sliced, sym, YEAR)
        log.info("  #%d %s 贡献%.0f (%s) 涨幅%s 成交额%s",
                 i, sym, c, _pct(c / gain_2025) if gain_2025 else "?",
                 _pct(ret), "-" if turnover is None else f"{turnover/1e6:.1f}M")


if __name__ == "__main__":
    main()
