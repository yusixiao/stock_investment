"""归因 2023 —— 冠军 PE≤15 唯一既亏钱又跑输恒指的坏年(只读,不改策略)。

背景:R20 年度拆解显示 BASE_G25 在 2023 −20.74%(恒指 −13.82%,超额 −6.92%),
是 17 年里唯一"既亏钱又跑输恒指"的年份;其余 5 个熊市年(2011/2015/2018/2021/2022)
策略均跑赢恒指(MA90 趋势过滤防守有效)。冠军 pe15 在 2023 约 −15.83%,同样反常。

本脚本对**冠军 PE≤15**跑一次连续回测(2010→2026,确保 5 年 CAGR lookback +
MA90 预热充分),然后只截取 2023 做归因,回答四问:

  Q1 年内净值轨迹:2023 是单边阴跌还是先涨后崩(bull trap)?何时最大回撤?
  Q2 标的归因:2023 亏损集中在少数标的还是普遍?per-symbol 实现/浮动盈亏。
  Q3 行业归因:哪些 sector 拖累最大?是否扎堆易受冲击行业?
  Q4 cohort 归因:6-2022 建仓持到 2023 上半年的一批 vs 6-2023 新建仓下半年的一批,
     哪一批更拖累?(回答"是踏空反弹/追高被套"还是"防守失灵")
  Q5 趋势 whipsaw:2023 内 round trip 笔数 / 平均持有天数,是否被 MA90 反复甩出。

对照:恒指 2023 月末收盘序列(看形态——2023 恒指 1 月强反弹后长阴,典型 bull trap,
正是 MA90 这类中期均线最容易被骗的形态)。

输出 exported/diagnose_2023.{md,json}。

用法(后台):
  python scripts/bg_launch.py logs/diagnose_2023.log python scripts/diagnose_2023.py
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.duckdb_store import get_store
from strategies.deployed.hk_garp_strategy import HkGarpStrategy
from strategies.utils import growth_hk, hk_industry

try:
    from services import stock_index
except Exception:
    stock_index = None

START, END = "2010-01-01", "2026-06-01"
YEAR = "2023"
TAG = "champion_pe15"

# 冠军生效参数(与 R21/R23/R24 一致)
CHAMPION_PE15 = {
    "top_n": 12, "min_amount_hkd": 1e7, "rebalance_months": [6],
    "cagr_years": 5, "trend_ma_days": 90,
    "require_industry": True, "max_per_sector": 2,
    "pe_max": 15.0,
}


def _name(sym):
    if stock_index is None:
        return ""
    try:
        return stock_index.get_name(sym) or ""
    except Exception:
        return ""


def _pct(x):
    return f"{x * 100:.2f}%" if isinstance(x, (int, float)) else str(x)


def _in_2023(d):
    return isinstance(d, str) and d[:4] == YEAR


def _overlaps_2023(entry, exit_):
    """round trip 的持有区间是否与 2023 有交集。"""
    if not isinstance(entry, str):
        return False
    e = entry[:10]
    x = exit_[:10] if isinstance(exit_, str) and exit_ else "9999-12-31"
    return e <= f"{YEAR}-12-31" and x >= f"{YEAR}-01-01"


def _hsi_2023_monthly():
    """恒指 2023 各月末收盘 + 全年/年内最大回撤,看 bull trap 形态。"""
    df = get_store().query_index("HK", "HSI", "2022-12-01", "2023-12-31")
    if df is None or df.empty or "close" not in df.columns:
        return None
    by_month = {}
    closes_2023 = []
    for d_str, c in zip(df["date"], df["close"]):
        d = str(d_str)[:10]
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        by_month[d[:7]] = (d, c)  # 月末覆盖
        if d[:4] == YEAR:
            closes_2023.append((d, c))
    months = sorted(by_month)
    rows = []
    prev = None
    for m in months:
        d, c = by_month[m]
        mom = (c / prev - 1) if prev else None
        rows.append({"month": m, "date": d, "close": round(c, 2), "mom": mom})
        prev = c
    # 年内峰谷
    peak = closes_2023[0][1] if closes_2023 else 0
    peak_d = closes_2023[0][0] if closes_2023 else ""
    worst_dd = 0.0
    worst_d = ""
    for d, c in closes_2023:
        if c > peak:
            peak, peak_d = c, d
        dd = (peak - c) / peak if peak > 0 else 0
        if dd > worst_dd:
            worst_dd, worst_d = dd, d
    yr_ret = (closes_2023[-1][1] / by_month["2022-12"][1] - 1) if closes_2023 else None
    return {
        "monthly": rows,
        "year_return": yr_ret,
        "intra_year_mdd": worst_dd,
        "mdd_trough_date": worst_d,
        "high_date": peak_d,
    }


def _equity_2023(eq):
    """从 equity_curve 截取 2023 段:年初/年末/年内峰谷/最大回撤位置。"""
    base = None  # 2022 末净值做基线
    pts = []
    for pt in eq:
        d = pt["date"][:10]
        v = float(pt["value"])
        if d < f"{YEAR}-01-01":
            base = v  # 持续覆盖到 2022 末
        elif d <= f"{YEAR}-12-31":
            pts.append((d, v))
    if not pts:
        return None
    start_v = base if base else pts[0][1]
    end_v = pts[-1][1]
    peak, peak_d = pts[0][1], pts[0][0]
    trough, trough_d = pts[0][1], pts[0][0]
    worst_dd, worst_d, worst_peak_d = 0.0, "", ""
    cur_peak, cur_peak_d = pts[0][1], pts[0][0]
    high, high_d = pts[0][1], pts[0][0]
    low, low_d = pts[0][1], pts[0][0]
    for d, v in pts:
        if v > high:
            high, high_d = v, d
        if v < low:
            low, low_d = v, d
        if v > cur_peak:
            cur_peak, cur_peak_d = v, d
        dd = (cur_peak - v) / cur_peak if cur_peak > 0 else 0
        if dd > worst_dd:
            worst_dd, worst_d, worst_peak_d = dd, d, cur_peak_d
    return {
        "base_2022_end": round(start_v, 2),
        "end_2023": round(end_v, 2),
        "year_return": end_v / start_v - 1 if start_v else None,
        "intra_high": round(high, 2), "intra_high_date": high_d,
        "intra_low": round(low, 2), "intra_low_date": low_d,
        "max_drawdown": worst_dd,
        "mdd_peak_date": worst_peak_d,
        "mdd_trough_date": worst_d,
        "n_points": len(pts),
    }


def main():
    t0 = time.time()
    growth_hk.reset_cache()
    hk_industry.reset_cache()
    print(f"[{time.time()-t0:.0f}s] 加载 HK bundle ...", flush=True)
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    print(f"[{time.time()-t0:.0f}s] bundle {len(bundle.stock_data)} stocks", flush=True)
    sliced = data_cache.slice_bundle(bundle, None, START, END)

    strat = HkGarpStrategy(param_overrides=CHAMPION_PE15)
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
    print(f"[{time.time()-t0:.0f}s] running {TAG} continuous ...", flush=True)
    result = engine.run()
    print(f"[{time.time()-t0:.0f}s] backtest done", flush=True)

    metrics = result["metrics"]
    round_trips = result.get("trades", [])
    eq = result["equity_curve"]

    # ---- Q1 年内净值轨迹 ----
    eq2023 = _equity_2023(eq)

    # ---- 选出与 2023 有交集的 round trips ----
    active = [rt for rt in round_trips
              if _overlaps_2023(rt.get("entry_date"), rt.get("exit_date"))]
    # 2023 内平仓的(已实现盈亏落在 2023)
    closed_2023 = [rt for rt in active if _in_2023(rt.get("exit_date"))]

    # ---- Q2 标的归因(基于 2023 内平仓的 round trip 实现盈亏) ----
    per_sym = defaultdict(lambda: {"pnl": 0.0, "cost": 0.0, "n": 0})
    for rt in closed_2023:
        s = rt["symbol"]
        cost = rt["entry_price"] * rt["shares"]
        per_sym[s]["pnl"] += rt["pnl"]
        per_sym[s]["cost"] += cost
        per_sym[s]["n"] += 1
    sym_rows = []
    for s, d in per_sym.items():
        sym_rows.append({
            "symbol": s, "name": _name(s),
            "sector": hk_industry.get_sector(s) or "",
            "pnl": round(d["pnl"], 2), "cost": round(d["cost"], 2),
            "ret_on_cost": round(d["pnl"] / d["cost"], 4) if d["cost"] > 0 else 0.0,
            "round_trips": d["n"],
        })
    sym_rows.sort(key=lambda r: r["pnl"])

    # ---- Q3 行业归因 ----
    sector_pnl = defaultdict(lambda: {"pnl": 0.0, "n": 0})
    for r in sym_rows:
        sec = r["sector"] or "__UNKNOWN__"
        sector_pnl[sec]["pnl"] += r["pnl"]
        sector_pnl[sec]["n"] += 1
    sector_rows = sorted(
        ({"sector": s, "pnl": round(d["pnl"], 2), "n_symbols": d["n"]}
         for s, d in sector_pnl.items()),
        key=lambda r: r["pnl"])

    # ---- Q4 cohort 归因(按 entry_date 所属调仓年) ----
    cohort = defaultdict(lambda: {"pnl": 0.0, "n": 0})
    for rt in closed_2023:
        ed = rt.get("entry_date", "")
        cohort_year = ed[:4] if isinstance(ed, str) else "?"
        cohort[cohort_year]["pnl"] += rt["pnl"]
        cohort[cohort_year]["n"] += 1
    cohort_rows = sorted(
        ({"entry_year": y, "pnl": round(d["pnl"], 2), "n_round_trips": d["n"]}
         for y, d in cohort.items()),
        key=lambda r: r["entry_year"])

    # ---- Q5 趋势 whipsaw ----
    n_closed = len(closed_2023)
    hold_days = [rt.get("hold_days", 0) for rt in closed_2023 if rt.get("hold_days")]
    avg_hold = sum(hold_days) / len(hold_days) if hold_days else 0
    short_trades = sum(1 for h in hold_days if h < 90)  # 持有 <3 月,疑似被甩出
    realized_2023 = round(sum(rt["pnl"] for rt in closed_2023), 2)
    wins = sum(1 for rt in closed_2023 if rt["pnl"] > 0)

    hsi = _hsi_2023_monthly()

    out = {
        "tag": TAG, "overrides": CHAMPION_PE15, "year": YEAR,
        "full_metrics": metrics,
        "equity_2023": eq2023,
        "hsi_2023": hsi,
        "realized_pnl_2023": realized_2023,
        "n_round_trips_closed_2023": n_closed,
        "n_wins": wins,
        "win_rate": round(wins / n_closed, 4) if n_closed else None,
        "avg_hold_days": round(avg_hold, 1),
        "n_short_trades_lt90d": short_trades,
        "cohort_attribution": cohort_rows,
        "sector_attribution": sector_rows,
        "per_symbol_worst15": sym_rows[:15],
        "per_symbol_best10": sym_rows[-10:][::-1],
    }
    exp = ROOT / "exported"
    exp.mkdir(exist_ok=True)
    (exp / "diagnose_2023.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- markdown ----
    md = []
    md.append(f"# 2023 归因 —— 冠军 {TAG}(唯一既亏钱又跑输恒指年)\n")
    md.append(f"> 连续回测 {START}→{END} 截取 {YEAR} | overrides={CHAMPION_PE15}\n")
    md.append(f"> 全期:年化 {_pct(metrics.get('annualized_return'))} / "
              f"Sharpe {metrics.get('sharpe_ratio')} / MDD {_pct(metrics.get('max_drawdown'))}\n")

    md.append("\n## Q1 2023 年内净值轨迹\n")
    if eq2023:
        md.append(f"- 2022 末基线净值 {eq2023['base_2022_end']:,.0f} → 2023 末 "
                  f"{eq2023['end_2023']:,.0f},**全年 {_pct(eq2023['year_return'])}**\n")
        md.append(f"- 年内高点 {eq2023['intra_high']:,.0f}({eq2023['intra_high_date']})、"
                  f"低点 {eq2023['intra_low']:,.0f}({eq2023['intra_low_date']})\n")
        md.append(f"- 年内最大回撤 **{_pct(eq2023['max_drawdown'])}** "
                  f"(峰 {eq2023['mdd_peak_date']} → 谷 {eq2023['mdd_trough_date']})\n")

    md.append("\n## 恒指 2023 形态对照(bull trap 检验)\n")
    if hsi:
        md.append(f"- 恒指全年 **{_pct(hsi['year_return'])}**,年内最大回撤 "
                  f"{_pct(hsi['intra_year_mdd'])}(高点 {hsi['high_date']} → 谷 {hsi['mdd_trough_date']})\n")
        md.append("\n| 月份 | 月末收盘 | 环比 |\n|---|---|---|\n")
        for r in hsi["monthly"]:
            md.append(f"| {r['month']} | {r['close']:,.0f} | {_pct(r['mom']) if r['mom'] is not None else '-'} |\n")

    md.append("\n## Q5 趋势 whipsaw 检验\n")
    md.append(f"- 2023 内平仓 round trip **{n_closed} 笔**,胜率 "
              f"{_pct(out['win_rate']) if out['win_rate'] is not None else '-'},"
              f"已实现盈亏 **{realized_2023:,.0f}**\n")
    md.append(f"- 平均持有 **{avg_hold:.0f} 天**;其中持有 <90 天(疑似被趋势甩出)"
              f"**{short_trades} 笔**\n")

    md.append("\n## Q4 cohort 归因(按建仓年份)\n")
    md.append("| 建仓年 | 2023 内平仓笔数 | 已实现盈亏 |\n|---|---|---|\n")
    for r in cohort_rows:
        md.append(f"| {r['entry_year']} | {r['n_round_trips']} | {r['pnl']:,.0f} |\n")
    md.append("> 6-2022 cohort = 持到 2023 上半年(追高被套/防守失灵);"
              "6-2023 cohort = 下半年新建仓。\n")

    md.append("\n## Q3 行业归因(2023 已实现盈亏,升序=最拖累在前)\n")
    md.append("| sector | 标的数 | 已实现盈亏 |\n|---|---|---|\n")
    for r in sector_rows:
        md.append(f"| {r['sector']} | {r['n_symbols']} | {r['pnl']:,.0f} |\n")

    md.append("\n## Q2 标的归因 —— 最拖累 15 只\n")
    md.append("| symbol | name | sector | rt | ret_on_cost | pnl |\n|---|---|---|---|---|---|\n")
    for r in sym_rows[:15]:
        md.append(f"| {r['symbol']} | {r['name']} | {r['sector']} | {r['round_trips']} | "
                  f"{_pct(r['ret_on_cost'])} | {r['pnl']:,.0f} |\n")
    md.append("\n## Q2 标的归因 —— 最赚 10 只\n")
    md.append("| symbol | name | sector | rt | ret_on_cost | pnl |\n|---|---|---|---|---|---|\n")
    for r in sym_rows[-10:][::-1]:
        md.append(f"| {r['symbol']} | {r['name']} | {r['sector']} | {r['round_trips']} | "
                  f"{_pct(r['ret_on_cost'])} | {r['pnl']:,.0f} |\n")

    (exp / "diagnose_2023.md").write_text("".join(md), encoding="utf-8")
    print(f"[{time.time()-t0:.0f}s] wrote exported/diagnose_2023.{{md,json}}", flush=True)
    print(f"  2023 closed_rt={n_closed} realized={realized_2023:,.0f} "
          f"avg_hold={avg_hold:.0f}d short<90d={short_trades}", flush=True)


if __name__ == "__main__":
    main()
