"""导出冠军策略 R21_pe15(BASE_R14 + pe_max=15)2010-2026 全部交易(只读)。

输出 exported/champion_trades_r21_pe15.md:
  1. 交易明细表:日期 | 代码 | 名称 | 方向(买/卖) | 数量 | 价格(港币)
     —— 用户指定列为「代码 | 方向 | 数量 | 价格」,这里额外前置「日期」「名称」
        以便 16 年跨度的逐笔流水可按时间排序、可读。
  2. 交易总结表:代码 | 名称 | 持仓 | 价格(最新交易日收盘) | 已实现利润 | 未实现利润 | 收益率
     —— 持仓 = 末日仍持有股数(全清则 0);
        已实现利润 = 该代码所有 round-trip 净盈亏合计(已扣佣金/印花税);
        未实现利润 = 仍持有部分 (最新价 - 持仓成本) × 股数;
        收益率 = (已实现 + 未实现) / 累计买入成本(该代码全部买入金额)。

价格口径与回测一致:成交价 = 上一段说明书所述 (open+close)/2 中间价 ± 滑点(broker 已计入)。
不修改任何数据。
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
from strategies.examples.hk_garp_strategy import HkGarpStrategy
from strategies.utils import growth_hk, hk_industry

try:
    from services import stock_index
except Exception:
    stock_index = None

START, END = "2010-01-01", "2026-06-01"
TAG = "R21_pe15"
BASE_R14 = {
    "top_n": 12, "min_amount_hkd": 1e7, "rebalance_months": [6],
    "cagr_years": 5, "trend_ma_days": 90,
    "require_industry": True, "max_per_sector": 2,
}
OVERRIDES = {**BASE_R14, "pe_max": 15.0}


_HK_NAMES: dict[str, str] | None = None


def _load_hk_names() -> dict[str, str]:
    """从 hk_industry.parquet 的 name 列建 code(无 .HK)→ 名称 映射。"""
    global _HK_NAMES
    if _HK_NAMES is not None:
        return _HK_NAMES
    _HK_NAMES = {}
    try:
        import pandas as pd
        from backend.config import MARKET_DIR
        p = MARKET_DIR / "HK" / "membership" / "hk_industry.parquet"
        df = pd.read_parquet(p, columns=["code", "name"])
        for code, name in zip(df["code"], df["name"]):
            if name is not None and not pd.isna(name):
                _HK_NAMES[str(code).strip().upper().removesuffix(".HK")] = str(name)
    except Exception:
        pass
    return _HK_NAMES


def _name(sym: str) -> str:
    key = str(sym).strip().upper().removesuffix(".HK")
    nm = _load_hk_names().get(key)
    if nm:
        return nm
    if stock_index is not None:
        try:
            return stock_index.get_name(sym) or ""
        except Exception:
            return ""
    return ""


def _last_close(df):
    """取最新交易日收盘价(按 date 取最大行)。"""
    if df is None or len(df) == 0:
        return None
    try:
        row = df.loc[df["date"].idxmax()] if "date" in df.columns else df.iloc[-1]
        return float(row["close"])
    except Exception:
        try:
            return float(df.iloc[-1]["close"])
        except Exception:
            return None


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

    # 末日仍持有的仓位(代码 -> {shares, cost})
    final_positions = {}
    for sym, pos in engine._broker.portfolio.positions.items():
        final_positions[sym] = {"shares": int(pos.shares), "cost": float(pos.cost)}
    final_cash = float(engine._broker.portfolio.cash)

    # 逐笔交易明细(按日期、再按代码排序)
    detail = sorted(
        raw_trades, key=lambda t: (t.get("date", ""), t.get("symbol", ""))
    )

    # per-symbol 聚合
    realized = defaultdict(float)        # round-trip 净盈亏合计
    buy_cost = defaultdict(float)        # 累计买入金额(price*shares)
    n_buy = defaultdict(int)
    n_sell = defaultdict(int)
    for rt in round_trips:
        realized[rt["symbol"]] += float(rt["pnl"])
    for tr in raw_trades:
        if tr["direction"] == "buy":
            buy_cost[tr["symbol"]] += float(tr["amount"])
            n_buy[tr["symbol"]] += 1
        else:
            n_sell[tr["symbol"]] += 1

    all_syms = sorted(set(buy_cost) | set(realized) | set(final_positions))

    summary = []
    for s in all_syms:
        last_px = _last_close(sliced.stock_data.get(s))
        held = final_positions.get(s)
        hold_shares = held["shares"] if held else 0
        unrealized = 0.0
        if held and last_px is not None:
            unrealized = (last_px - held["cost"]) * held["shares"]
        rpnl = realized.get(s, 0.0)
        cost_basis = buy_cost.get(s, 0.0)
        ret = (rpnl + unrealized) / cost_basis if cost_basis > 0 else 0.0
        summary.append({
            "symbol": s,
            "name": _name(s),
            "hold_shares": hold_shares,
            "last_price": round(last_px, 4) if last_px is not None else None,
            "realized": round(rpnl, 2),
            "unrealized": round(unrealized, 2),
            "total_pnl": round(rpnl + unrealized, 2),
            "buy_cost": round(cost_basis, 2),
            "ret": round(ret, 4),
            "n_buy": n_buy.get(s, 0),
            "n_sell": n_sell.get(s, 0),
        })
    # 总收益从高到低
    summary.sort(key=lambda r: r["total_pnl"], reverse=True)

    tot_realized = sum(r["realized"] for r in summary)
    tot_unreal = sum(r["unrealized"] for r in summary)

    out = {
        "tag": TAG, "overrides": OVERRIDES, "period": f"{START}~{END}",
        "metrics": metrics,
        "n_trades": len(raw_trades),
        "n_symbols": len(all_syms),
        "n_open_positions": len(final_positions),
        "final_cash": round(final_cash, 2),
        "total_realized_pnl": round(tot_realized, 2),
        "total_unrealized_pnl": round(tot_unreal, 2),
        "trade_detail": detail,
        "summary": summary,
    }
    exp = ROOT / "exported"
    exp.mkdir(exist_ok=True)
    (exp / "champion_trades_r21_pe15.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- markdown ----------
    md = []
    md.append(f"# 冠军策略 {TAG} 全期交易清单(2010–2026)\n\n")
    md.append(f"> 策略:`HkGarpStrategy` | 参数:BASE_R14 + **pe_max=15** | "
              f"区间:{START} ~ {END}\n")
    md.append(f"> 全期年化 {metrics.get('annualized_return', 0)*100:.2f}% / "
              f"Sharpe {metrics.get('sharpe_ratio')} / "
              f"MDD {metrics.get('max_drawdown', 0)*100:.2f}%\n")
    md.append(f"> 单边成交事件 **{len(raw_trades)}** 笔 | 涉及标的 **{len(all_syms)}** 只 | "
              f"末日仍持有 **{len(final_positions)}** 只 | 末日现金 {final_cash:,.0f} HKD\n")
    md.append(f"> 价格口径:回测成交价 = (open+close)/2 中间价 ± 滑点(已含佣金万三/卖出印花税千一);"
              f"总结表「价格」列 = 各标的**最新交易日收盘价**(港币)\n\n")
    md.append("> 说明:交易明细列在用户指定的「代码/方向/数量/价格」基础上前置「日期」「名称」,"
              "便于按时间排序与辨识。\n\n")

    md.append("## 一、交易明细(逐笔,按日期排序)\n\n")
    md.append("| 日期 | 代码 | 名称 | 方向 | 数量 | 价格(HKD) |\n")
    md.append("|---|---|---|---|---:|---:|\n")
    for tr in detail:
        dirn = "买" if tr["direction"] == "buy" else "卖"
        md.append(f"| {tr.get('date','')} | {tr['symbol']} | {_name(tr['symbol'])} | "
                  f"{dirn} | {int(tr['shares']):,} | {float(tr['price']):.4f} |\n")

    md.append("\n## 二、交易总结(按总盈亏降序)\n\n")
    md.append("> 已实现利润 = 该代码全部 round-trip 净盈亏(已扣费);"
              "未实现利润 = 末日仍持有部分 (最新价−成本)×股数;"
              "收益率 = (已实现+未实现) / 累计买入成本。\n\n")
    md.append("| 代码 | 名称 | 持仓(股) | 价格(HKD) | 已实现利润 | 未实现利润 | 收益率 |\n")
    md.append("|---|---|---:|---:|---:|---:|---:|\n")
    for r in summary:
        px = f"{r['last_price']:.4f}" if r["last_price"] is not None else "—"
        unreal = f"{r['unrealized']:,.0f}" if r["hold_shares"] > 0 else "—"
        md.append(f"| {r['symbol']} | {r['name']} | {r['hold_shares']:,} | {px} | "
                  f"{r['realized']:,.0f} | {unreal} | {r['ret']*100:.2f}% |\n")
    md.append(f"\n**合计**:已实现利润 {tot_realized:,.0f} HKD | "
              f"未实现利润 {tot_unreal:,.0f} HKD | "
              f"末日现金 {final_cash:,.0f} HKD\n")

    (exp / "champion_trades_r21_pe15.md").write_text("".join(md), encoding="utf-8")
    print(f"[{time.time()-t0:.0f}s] wrote exported/champion_trades_r21_pe15.{{md,json}}",
          flush=True)
    print(f"  trades={len(raw_trades)} symbols={len(all_syms)} "
          f"open={len(final_positions)} realized={tot_realized:,.0f} "
          f"unreal={tot_unreal:,.0f}", flush=True)


if __name__ == "__main__":
    main()
