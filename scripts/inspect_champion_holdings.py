"""复盘干净冠军 R16_pe20 的实际交易标的(只读)。

目的(用户定稿的"退市股/PIT 行业"偏差事后复盘路径):
  1. 跑一次冠军配置(BASE_R14 + pe_max=20),dump 全部 round-trip + 持有过的 symbol;
  2. 按 symbol 聚合实现盈亏贡献,检查是否被极少数标的注水(phantom 残留风险);
  3. 标注幸存者逻辑:交易清单 = 当前仍上市的标的(by construction),
     无法"命中退市股"——偏差在缺失的退市标的,不在已交易清单;
  4. 输出 sector 分布,粗判是否过度集中于易被重分类的行业。

不修改任何数据。输出 exported/champion_holdings_r16_pe20.{md,json}。
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
from strategies.deployed.hk_garp_strategy import HkGarpStrategy
from strategies.utils import growth_hk, hk_industry

try:
    from services import stock_index
except Exception:
    stock_index = None

START, END = "2010-01-01", "2026-06-01"
TAG = "R16_pe20"
BASE_R14 = {
    "top_n": 12, "min_amount_hkd": 1e7, "rebalance_months": [6],
    "cagr_years": 5, "trend_ma_days": 90,
    "require_industry": True, "max_per_sector": 2,
}
OVERRIDES = {**BASE_R14, "pe_max": 20.0}


def _name(sym: str) -> str:
    if stock_index is None:
        return ""
    try:
        return stock_index.get_name(sym) or ""
    except Exception:
        return ""


def _pct(x):
    return f"{x * 100:.2f}%" if isinstance(x, (int, float)) else str(x)


def main():
    t0 = time.time()
    growth_hk.reset_cache()
    hk_industry.reset_cache()
    print(f"[{time.time()-t0:.0f}s] 加载 HK bundle ...", flush=True)
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    print(f"[{time.time()-t0:.0f}s] bundle {len(bundle.stock_data)} stocks", flush=True)
    sliced = data_cache.slice_bundle(bundle, None, START, END)

    strat = HkGarpStrategy(param_overrides=OVERRIDES)
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
    print(f"[{time.time()-t0:.0f}s] running {TAG} ...", flush=True)
    result = engine.run()
    print(f"[{time.time()-t0:.0f}s] done", flush=True)

    metrics = result["metrics"]
    round_trips = result.get("trades", [])
    raw_trades = result.get("raw_trades", [])
    held_symbols = sorted({t["symbol"] for t in raw_trades})

    # per-symbol 实现盈亏聚合(基于 round-trip)
    per_sym = defaultdict(lambda: {"pnl": 0.0, "cost": 0.0, "n": 0})
    for rt in round_trips:
        s = rt["symbol"]
        cost = rt["entry_price"] * rt["shares"]
        per_sym[s]["pnl"] += rt["pnl"]
        per_sym[s]["cost"] += cost
        per_sym[s]["n"] += 1

    rows = []
    for s, d in per_sym.items():
        rows.append({
            "symbol": s,
            "name": _name(s),
            "sector": hk_industry.get_sector(s) or "",
            "industry": hk_industry.get_industry(s) or "",
            "pnl": round(d["pnl"], 2),
            "cost": round(d["cost"], 2),
            "ret_on_cost": round(d["pnl"] / d["cost"], 4) if d["cost"] > 0 else 0.0,
            "round_trips": d["n"],
        })
    rows.sort(key=lambda r: r["pnl"], reverse=True)

    total_pnl = sum(r["pnl"] for r in rows)
    pos_pnl = sum(r["pnl"] for r in rows if r["pnl"] > 0)
    top1 = rows[0]["pnl"] / pos_pnl if pos_pnl > 0 and rows else 0.0
    top5 = sum(r["pnl"] for r in rows[:5]) / pos_pnl if pos_pnl > 0 else 0.0
    top10 = sum(r["pnl"] for r in rows[:10]) / pos_pnl if pos_pnl > 0 else 0.0

    # sector 分布(按正盈亏贡献)
    sector_pnl = defaultdict(float)
    sector_cnt = defaultdict(int)
    for r in rows:
        sec = r["sector"] or "__UNKNOWN__"
        sector_pnl[sec] += r["pnl"]
        sector_cnt[sec] += 1
    sector_rows = sorted(sector_pnl.items(), key=lambda kv: kv[1], reverse=True)

    out = {
        "tag": TAG,
        "overrides": OVERRIDES,
        "period": f"{START}~{END}",
        "metrics": metrics,
        "n_held_symbols": len(held_symbols),
        "n_round_trip_symbols": len(rows),
        "total_realized_pnl": round(total_pnl, 2),
        "concentration": {
            "top1_share_of_positive_pnl": round(top1, 4),
            "top5_share_of_positive_pnl": round(top5, 4),
            "top10_share_of_positive_pnl": round(top10, 4),
        },
        "top_contributors": rows[:20],
        "worst_contributors": rows[-10:],
        "sector_distribution": [
            {"sector": s, "n_symbols": sector_cnt[s], "pnl": round(p, 2)}
            for s, p in sector_rows
        ],
        "held_symbols": held_symbols,
    }

    exp = ROOT / "exported"
    exp.mkdir(exist_ok=True)
    (exp / "champion_holdings_r16_pe20.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # markdown
    md = []
    md.append(f"# 干净冠军 {TAG} 交易标的复盘\n")
    md.append(f"> 区间 {START}~{END} | overrides={OVERRIDES}\n")
    md.append(f"> 年化 {_pct(metrics.get('annualized_return'))} / Sharpe "
              f"{metrics.get('sharpe_ratio')} / MDD {_pct(metrics.get('max_drawdown'))}\n")
    md.append("## 关键结论\n")
    md.append(f"- 持有过的标的(含未平仓): **{len(held_symbols)}** 只;"
              f"有 round-trip 实现盈亏的: **{len(rows)}** 只\n")
    md.append(f"- 实现盈亏合计: **{total_pnl:,.0f}**(正贡献合计 {pos_pnl:,.0f})\n")
    md.append(f"- **集中度**:第一大贡献占正盈亏 **{_pct(top1)}**,前 5 占 **{_pct(top5)}**,"
              f"前 10 占 **{_pct(top10)}**\n")
    md.append("- ⚠️ **幸存者逻辑**:本清单 100% 是当前仍上市标的(标的池 = 现存 H 股快照),"
              "**by construction 不含退市股**;偏差来自**缺失的退市标的**(无法在已交易清单中体现),"
              "而非清单内混入退市股。\n")
    md.append("\n## Top20 盈亏贡献\n")
    md.append("| symbol | name | sector | round_trips | ret_on_cost | pnl |\n|---|---|---|---|---|---|\n")
    for r in rows[:20]:
        md.append(f"| {r['symbol']} | {r['name']} | {r['sector']} | {r['round_trips']} | "
                  f"{_pct(r['ret_on_cost'])} | {r['pnl']:,.0f} |\n")
    md.append("\n## 最差 10 标的\n")
    md.append("| symbol | name | sector | round_trips | ret_on_cost | pnl |\n|---|---|---|---|---|---|\n")
    for r in rows[-10:]:
        md.append(f"| {r['symbol']} | {r['name']} | {r['sector']} | {r['round_trips']} | "
                  f"{_pct(r['ret_on_cost'])} | {r['pnl']:,.0f} |\n")
    md.append("\n## sector 分布(按正盈亏贡献)\n")
    md.append("| sector | n_symbols | pnl |\n|---|---|---|\n")
    for s, p in sector_rows:
        md.append(f"| {s} | {sector_cnt[s]} | {p:,.0f} |\n")
    (exp / "champion_holdings_r16_pe20.md").write_text("".join(md), encoding="utf-8")

    print(f"[{time.time()-t0:.0f}s] wrote exported/champion_holdings_r16_pe20.{{md,json}}", flush=True)
    print(f"  held={len(held_symbols)} rt_syms={len(rows)} "
          f"top1={top1:.1%} top5={top5:.1%} top10={top10:.1%}", flush=True)


if __name__ == "__main__":
    main()
