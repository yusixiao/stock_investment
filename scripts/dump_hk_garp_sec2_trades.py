"""导出「进取 Top12+趋势90+每行业≤2(纯分散)」配置的交易明细到 Excel。

配置 = R11_agg_sec2 / R12_agg_sec2:
  {**BASE8, top_n=12, trend_ma_days=90, max_per_sector=2}
  即 top_n=12 / min_amount_hkd=1e7 / rebalance_months=[6](年度) /
     cagr_years=5 / trend_ma_days=90 / max_per_sector=2
区间 2010-01-01 → 2026-06-01,全 H股,无 require_industry(纯分散,无额外选择偏差)。

输出 exported/hk_garp_sec2_trades.xlsx,5 个 sheet:
  1. 概览       —— 配置参数 + 回测指标
  2. 买卖事件   —— 逐笔成交(raw_trades:日期/方向/代码/名称/行业/价/股数/金额/费)
  3. 持仓快照   —— 每个成交日收盘后的完整持仓(长格式)
  4. 完整交易   —— round trips(买入→卖出配对)+ 期末仍持有标记「持有中」
  5. 个股汇总   —— 每只股票累计已实现盈亏 / 笔数 / 胜率 / 入选次数

格式参照 scripts/dump_r20_trades.py(A股 R20),但走 HK GARP 的 BacktestEngine 路径。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from services.backtest import data_cache  # noqa: E402
from services.backtest.engine import BacktestEngine  # noqa: E402
from strategies.utils import growth_hk, hk_industry  # noqa: E402
from strategies.examples.hk_garp_strategy import HkGarpStrategy  # noqa: E402

START = "2010-01-01"
END = "2026-06-01"
OUT_XLSX = ROOT / "exported" / "hk_garp_sec2_trades.xlsx"

BASE7 = {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5}
BASE8 = {**BASE7, "trend_ma_days": 120}
CONFIG = {**BASE8, "top_n": 12, "trend_ma_days": 90, "max_per_sector": 2}


def _load_name_map() -> dict:
    """data/market/HK/stock_list.csv → {code(.HK): name}。"""
    path = ROOT / "data" / "market" / "HK" / "stock_list.csv"
    if not path.exists():
        print(f"⚠️ 未找到 {path},名称留空")
        return {}
    df = pd.read_csv(path, dtype=str)
    return {
        r["code"]: r.get("name")
        for _, r in df.iterrows()
        if r.get("code") and not pd.isna(r.get("name"))
    }


def main():
    print("加载 HK bundle ...")
    t0 = time.time()
    growth_hk.reset_cache()
    hk_industry.reset_cache()
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    print(f"  bundle {len(bundle.stock_data)} 只,{time.time() - t0:.1f}s")
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    print(
        f"  sliced {len(sliced.stock_data)} 只 iter[{sliced.iter_start_idx},"
        f"{sliced.iter_end_idx}] {START}→{END}"
    )

    name_map = _load_name_map()

    def nm(code: str) -> str:
        return name_map.get(code, "") or ""

    def sec(code: str) -> str:
        return hk_industry.get_sector(code) or ""

    print("运行回测(Top12+趋势90+每行业≤2)...")
    t0 = time.time()
    strat = HkGarpStrategy(param_overrides=CONFIG)
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
    result = engine.run()
    m = result["metrics"]
    raw = result["raw_trades"]
    rts = result["trades"]
    end_prices = result.get("end_prices", {})
    print(
        f"  完成 {time.time() - t0:.1f}s | 年化={m.get('annualized_return', 0):.2%} "
        f"总收益={m.get('total_return', 0):.2%} MDD={m.get('max_drawdown', 0):.2%} "
        f"Sharpe={m.get('sharpe_ratio', 0):.2f} | {len(raw)} 笔成交 / {len(rts)} 笔完整交易"
    )

    # ---------- Sheet 1 概览 ----------
    overview = pd.DataFrame(
        [
            ("策略", "进取 Top12+趋势90+每行业≤2(纯分散)"),
            ("代号", "R11_agg_sec2 / R12_agg_sec2"),
            ("区间", f"{START} → {END}"),
            ("股票池", f"全 H股({len(bundle.stock_data)} 只)"),
            ("top_n(持仓数)", CONFIG["top_n"]),
            ("trend_ma_days(趋势线)", CONFIG["trend_ma_days"]),
            ("max_per_sector(每行业上限)", CONFIG["max_per_sector"]),
            ("min_amount_hkd(流动性门槛)", f"{CONFIG['min_amount_hkd']:.0f} 港元/日"),
            ("rebalance_months(调仓月)", str(CONFIG["rebalance_months"]) + " (年度)"),
            ("cagr_years(成长窗口)", CONFIG["cagr_years"]),
            ("require_industry", "False(纯分散,无龙头偏差)"),
            ("—", "—"),
            ("年化收益率", f"{m.get('annualized_return', 0):.2%}"),
            ("总收益率", f"{m.get('total_return', 0):.2%}"),
            ("最大回撤", f"{m.get('max_drawdown', 0):.2%}"),
            ("Sharpe", f"{m.get('sharpe_ratio', 0):.2f}"),
            ("胜率", f"{m.get('win_rate', 0):.2%}"),
            ("成交笔数(单边)", len(raw)),
            ("完整交易笔数(配对)", len(rts)),
            (
                "免责声明",
                "无退市股 → 存在幸存者偏差,结果偏乐观;行业分类用今日快照(无 PIT)",
            ),
        ],
        columns=["项目", "值"],
    )

    # ---------- Sheet 2 买卖事件(raw_trades) ----------
    ev_rows = []
    for t in sorted(raw, key=lambda x: (x["date"], x["symbol"])):
        ev_rows.append(
            {
                "日期": t["date"],
                "方向": "买入" if t["direction"] == "buy" else "卖出",
                "代码": t["symbol"],
                "名称": nm(t["symbol"]),
                "行业": sec(t["symbol"]),
                "成交价": round(float(t["price"]), 4),
                "股数": int(t["shares"]),
                "金额": round(float(t["amount"]), 2),
                "佣金": round(float(t.get("commission", 0)), 2),
                "印花税": round(float(t.get("tax", 0)), 2),
            }
        )
    events = pd.DataFrame(ev_rows)

    # ---------- Sheet 3 持仓快照(每个成交日收盘后) ----------
    pos: dict[str, dict] = {}  # code -> {shares, cost_amount}
    snap_rows = []
    for date in sorted({t["date"] for t in raw}):
        day_trades = [t for t in raw if t["date"] == date]
        for t in day_trades:
            c = t["symbol"]
            if t["direction"] == "buy":
                p = pos.setdefault(c, {"shares": 0, "cost": 0.0})
                p["shares"] += int(t["shares"])
                p["cost"] += float(t["amount"]) + float(t.get("commission", 0))
            else:
                p = pos.get(c)
                if p:
                    sold = int(t["shares"])
                    if p["shares"] > 0:
                        p["cost"] *= max(p["shares"] - sold, 0) / p["shares"]
                    p["shares"] -= sold
                    if p["shares"] <= 0:
                        pos.pop(c, None)
        for c, p in sorted(pos.items()):
            avg = p["cost"] / p["shares"] if p["shares"] else 0.0
            snap_rows.append(
                {
                    "调仓日": date,
                    "代码": c,
                    "名称": nm(c),
                    "行业": sec(c),
                    "持股数": p["shares"],
                    "成本价": round(avg, 4),
                }
            )
    snapshots = pd.DataFrame(snap_rows)

    # ---------- Sheet 4 完整交易(round trips + 期末持有中) ----------
    rt_rows = []
    for rt in rts:
        rt_rows.append(
            {
                "代码": rt["symbol"],
                "名称": nm(rt["symbol"]),
                "行业": sec(rt["symbol"]),
                "买入日": rt["entry_date"],
                "卖出日": rt["exit_date"],
                "买入价": round(float(rt["entry_price"]), 4),
                "卖出价": round(float(rt["exit_price"]), 4),
                "股数": int(rt["shares"]),
                "盈亏": round(float(rt["pnl"]), 2),
                "收益率": round(float(rt["pnl_pct"]), 4),
                "持有天数": rt["hold_days"],
                "状态": "已平仓",
            }
        )
    # 期末仍持有(未平仓)用 end_prices 估值
    for c, p in sorted(pos.items()):
        if p["shares"] <= 0:
            continue
        avg = p["cost"] / p["shares"]
        last = end_prices.get(c)
        pnl = (last - avg) * p["shares"] if last else None
        rt_rows.append(
            {
                "代码": c,
                "名称": nm(c),
                "行业": sec(c),
                "买入日": "",
                "卖出日": END,
                "买入价": round(avg, 4),
                "卖出价": round(float(last), 4) if last else "",
                "股数": p["shares"],
                "盈亏": round(float(pnl), 2) if pnl is not None else "",
                "收益率": round((last - avg) / avg, 4) if last and avg else "",
                "持有天数": "",
                "状态": "持有中",
            }
        )
    roundtrips = pd.DataFrame(rt_rows)

    # ---------- Sheet 5 个股汇总 ----------
    sum_rows = []
    by_code: dict[str, list] = {}
    for rt in rts:
        by_code.setdefault(rt["symbol"], []).append(rt)
    freq = (
        snapshots.groupby("代码").size().to_dict() if not snapshots.empty else {}
    )
    all_codes = set(by_code) | set(freq)
    for c in sorted(all_codes):
        trades_c = by_code.get(c, [])
        wins = sum(1 for x in trades_c if x["pnl"] > 0)
        total_pnl = sum(x["pnl"] for x in trades_c)
        sum_rows.append(
            {
                "代码": c,
                "名称": nm(c),
                "行业": sec(c),
                "完整交易笔数": len(trades_c),
                "累计已实现盈亏": round(total_pnl, 2),
                "胜率": round(wins / len(trades_c), 4) if trades_c else "",
                "入选快照次数": int(freq.get(c, 0)),
            }
        )
    summary = pd.DataFrame(sum_rows).sort_values(
        "累计已实现盈亏", ascending=False, ignore_index=True
    )

    # ---------- 写 Excel ----------
    OUT_XLSX.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="概览", index=False)
        events.to_excel(w, sheet_name="买卖事件", index=False)
        snapshots.to_excel(w, sheet_name="持仓快照", index=False)
        roundtrips.to_excel(w, sheet_name="完整交易", index=False)
        summary.to_excel(w, sheet_name="个股汇总", index=False)

    print(f"\n✅ 已导出 {OUT_XLSX}")
    print(
        f"   概览 / 买卖事件({len(events)}) / 持仓快照({len(snapshots)}) / "
        f"完整交易({len(roundtrips)}) / 个股汇总({len(summary)})"
    )


if __name__ == "__main__":
    main()
