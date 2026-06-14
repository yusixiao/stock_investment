"""R20 —— BASE_G25 连续回测(2010-2026)按日历年拆解年度收益率。

方案 A:不切独立窗口,而是跑一次连续 BASE_G25,从 equity_curve 按日历年
拆出每年收益率 + 年内最大回撤,并对照同年恒指(HSI)涨跌作为客观牛熊标签,
回答"牛熊市是否都能有不错收益率"。

为什么不切独立年度窗口:BASE_G25 6 月调仓,日历年(1月→1月)独立窗口每个都
从空仓起步、6 月才建仓 → 每年实际仅约 7 个月持仓,失真且不可比;且早期窗口
因 5 年 CAGR lookback 不足选不出股。连续回测拆解 = 实际部署策略的真实年度收益,
无空仓缺口、无重复预热、年与年连续可比(仅 2010 因首个调仓在 6 月,上半年为现金,
属策略真实行为而非失真)。

用法(后台):
  python scripts/bg_launch.py logs/hk_garp_r20.log python scripts/run_hk_garp_r20.py
"""

import json
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
log = logging.getLogger("hk_garp_r20")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.market_data.duckdb_store import get_store
from services.backtest.strategies.utils import growth_hk, hk_industry
from services.backtest.strategies.deployed.hk_garp_strategy import HkGarpStrategy

START = "2010-01-01"
END = "2026-06-01"
OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)

# R17 锁定的最优选股内核(收益最高):BASE_R14 + 净利 CAGR≥25%
BASE_G25 = {
    "top_n": 12, "min_amount_hkd": 1e7, "rebalance_months": [6],
    "cagr_years": 5, "trend_ma_days": 90, "require_industry": True,
    "max_per_sector": 2, "np_cagr_min": 0.25,
}


def _pct(x):
    return "-" if x is None else f"{x * 100:+.2f}%"


def _year_end_values(equity_curve):
    """每个日历年的最后一个净值点 -> {year: (date, value)}。"""
    by_year = {}
    for pt in equity_curve:
        y = int(pt["date"][:4])
        # equity_curve 按时间升序,持续覆盖即得该年最后一点
        by_year[y] = (pt["date"], float(pt["value"]))
    return by_year


def _year_intra_mdd(equity_curve):
    """每个日历年内的最大回撤(峰谷,仅用年内点)-> {year: mdd_float(正数)}。"""
    pts_by_year = defaultdict(list)
    for pt in equity_curve:
        pts_by_year[int(pt["date"][:4])].append(float(pt["value"]))
    mdd = {}
    for y, vals in pts_by_year.items():
        peak = vals[0]
        worst = 0.0
        for v in vals:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > worst:
                worst = dd
        mdd[y] = worst
    return mdd


def _hsi_annual_returns():
    """恒指日历年收益率 {year: ret} + 年末点 {year: (date, close)}。"""
    df = get_store().query_index("HK", "HSI", START, END)
    if df is None or df.empty or "close" not in df.columns:
        log.warning("HSI 数据不可用,跳过牛熊标签")
        return {}, {}
    by_year = {}
    for d_str, c in zip(df["date"], df["close"]):
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        by_year[int(str(d_str)[:4])] = (str(d_str), c)
    years = sorted(by_year)
    rets = {}
    for i, y in enumerate(years):
        if i == 0:
            continue  # 无上一年末做基线
        prev_close = by_year[years[i - 1]][1]
        rets[y] = by_year[y][1] / prev_close - 1 if prev_close > 0 else None
    return rets, by_year


def main():
    growth_hk.reset_cache()
    hk_industry.reset_cache()
    log.info("加载 HK bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info("sliced %d stocks iter[%d,%d] %s→%s", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx, START, END)

    strat = HkGarpStrategy(param_overrides=BASE_G25)
    engine = BacktestEngine(
        strategy=strat,
        stock_data=sliced.stock_data,
        valuation_data=sliced.valuation_data,
        dividend_data=sliced.dividend_data,
        financial_data=sliced.financial_data,
        balance_data=sliced.balance_data,
        cashflow_data=sliced.cashflow_data,
        income_data=sliced.income_data,
        weekly_data=sliced.weekly_data,
        monthly_data=sliced.monthly_data,
        iter_start=sliced.iter_start_idx,
        iter_end=sliced.iter_end_idx,
        enable_decision_log=False,
    )
    log.info("running BASE_G25 continuous ...")
    t1 = time.time()
    result = engine.run()
    log.info("backtest done in %.1fs", time.time() - t1)

    m = result["metrics"]
    eq = result["equity_curve"]
    init_cap = float(engine._initial_capital)
    log.info("full-period annual=%s total=%s mdd=%s sharpe=%.2f",
             _pct(m.get("annualized_return")), _pct(m.get("total_return")),
             _pct(m.get("max_drawdown")), m.get("sharpe_ratio", 0))

    year_end = _year_end_values(eq)
    intra_mdd = _year_intra_mdd(eq)
    hsi_rets, _ = _hsi_annual_returns()

    years = sorted(year_end)
    rows = []
    prev_value = init_cap
    for y in years:
        end_date, end_val = year_end[y]
        ret = end_val / prev_value - 1 if prev_value > 0 else None
        hsi = hsi_rets.get(y)
        excess = (ret - hsi) if (ret is not None and hsi is not None) else None
        rows.append({
            "year": y,
            "end_date": end_date,
            "end_value": round(end_val, 2),
            "strategy_return": ret,
            "hsi_return": hsi,
            "excess": excess,
            "intra_year_mdd": intra_mdd.get(y),
        })
        prev_value = end_val

    payload = {
        "config": "BASE_G25",
        "params": BASE_G25,
        "period": f"{START}→{END}",
        "initial_capital": init_cap,
        "full_metrics": m,
        "annual": rows,
        "note": "2010 上半年为现金(首个调仓在 6 月),属策略真实行为",
    }
    (OUT_DIR / "hk_garp_r20_annual.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2))

    # ---- markdown 表 ----
    def label(strat_ret, hsi):
        if hsi is None:
            return "?"
        bull = hsi > 0.05
        bear = hsi < -0.05
        regime = "🐂牛" if bull else ("🐻熊" if bear else "震荡")
        return regime

    lines = [
        "# R20 —— BASE_G25 日历年收益拆解(连续回测)",
        "",
        f"区间 {START} → {END} | 全 H股 | 连续回测(非独立窗口)",
        "",
        f"全期:年化 **{_pct(m.get('annualized_return'))}** | "
        f"总收益 {_pct(m.get('total_return'))} | "
        f"最大回撤 {_pct(m.get('max_drawdown'))} | "
        f"Sharpe {m.get('sharpe_ratio', 0):.2f}",
        "",
        "> 方案 A:从连续回测净值曲线按日历年拆解,反映实际部署策略的真实年度收益。",
        "> 2010 上半年为现金(首个调仓在 6 月),属策略真实行为非失真。",
        "> 牛熊标签 = 同年恒指(HSI)日历年涨跌:>+5% 牛 / <-5% 熊 / 其余震荡。",
        "",
        "| 年份 | 市场(HSI) | 策略收益 | 恒指涨跌 | 超额 | 年内最大回撤 |",
        "|---|---|---|---|---|---|",
    ]
    win = 0
    n_cmp = 0
    for r in rows:
        mdd_cell = "-" if r["intra_year_mdd"] is None else f"{r['intra_year_mdd'] * 100:.2f}%"
        lines.append(
            f"| {r['year']} | {label(r['strategy_return'], r['hsi_return'])} | "
            f"**{_pct(r['strategy_return'])}** | {_pct(r['hsi_return'])} | "
            f"{_pct(r['excess'])} | {mdd_cell} |"
        )
        if r["excess"] is not None:
            n_cmp += 1
            if r["excess"] > 0:
                win += 1

    # 牛熊分组统计
    bull_rets = [r["strategy_return"] for r in rows
                 if r["hsi_return"] is not None and r["hsi_return"] > 0.05
                 and r["strategy_return"] is not None]
    bear_rets = [r["strategy_return"] for r in rows
                 if r["hsi_return"] is not None and r["hsi_return"] < -0.05
                 and r["strategy_return"] is not None]
    flat_rets = [r["strategy_return"] for r in rows
                 if r["hsi_return"] is not None
                 and -0.05 <= r["hsi_return"] <= 0.05
                 and r["strategy_return"] is not None]
    pos_years = [r["year"] for r in rows
                 if r["strategy_return"] is not None and r["strategy_return"] > 0]

    def _avg(xs):
        return sum(xs) / len(xs) if xs else None

    lines += [
        "",
        "## 牛熊分组",
        "",
        f"- 🐂 牛市年({len(bull_rets)} 年):平均策略收益 {_pct(_avg(bull_rets))}",
        f"- 🐻 熊市年({len(bear_rets)} 年):平均策略收益 {_pct(_avg(bear_rets))}",
        f"- 震荡年({len(flat_rets)} 年):平均策略收益 {_pct(_avg(flat_rets))}",
        f"- 正收益年份:{len(pos_years)}/{len(rows)} = {', '.join(map(str, pos_years))}",
        f"- 跑赢恒指:{win}/{n_cmp} 年",
    ]
    (OUT_DIR / "hk_garp_r20_annual.md").write_text("\n".join(lines))
    log.info("DONE -> exported/hk_garp_r20_annual.md (+ .json)")


if __name__ == "__main__":
    main()
