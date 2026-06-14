"""MaTangleValueStrategy 卖出策略变体矩阵回测(2010-2026)。

跑 9 个变体,横向对比 PE / MA 退出条件对总收益、年化、回撤、换手率的影响,
找出年化 ≥ 20% 的最优组合。

用法:
    python scripts/run_ma_tangle_matrix.py [START_DATE] [END_DATE] [VARIANT_IDS]
    例:python scripts/run_ma_tangle_matrix.py 2010-01-01 2026-05-23
        python scripts/run_ma_tangle_matrix.py 2010-01-01 2026-05-23 V0,V1,V6
"""

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("matrix")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.deployed.ma_tangle_value_strategy import MaTangleValueStrategy

# ---------- 变体矩阵 ----------
VARIANTS = [
    {
        "id": "V0",
        "sell_pe_pb_max": 0.0,
        "sell_below_ma": "none",
        "note": "baseline 永久持有",
    },
    {"id": "V1", "sell_pe_pb_max": 0.0, "sell_below_ma": "ma20", "note": "纯趋势 MA20"},
    {"id": "V2", "sell_pe_pb_max": 0.0, "sell_below_ma": "ma10", "note": "敏感 MA10"},
    {"id": "V3", "sell_pe_pb_max": 0.0, "sell_below_ma": "ma30", "note": "迟钝 MA30"},
    {
        "id": "V4",
        "sell_pe_pb_max": 33.0,
        "sell_below_ma": "none",
        "note": "纯估值 1.5x",
    },
    {"id": "V5", "sell_pe_pb_max": 44.0, "sell_below_ma": "none", "note": "宽估值 2x"},
    {"id": "V6", "sell_pe_pb_max": 33.0, "sell_below_ma": "ma20", "note": "PE+MA20"},
    {"id": "V7", "sell_pe_pb_max": 44.0, "sell_below_ma": "ma20", "note": "宽 PE+MA20"},
    {"id": "V8", "sell_pe_pb_max": 44.0, "sell_below_ma": "ma10", "note": "宽 PE+MA10"},
]

START = sys.argv[1] if len(sys.argv) > 1 else "2010-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-05-23"
SELECTED = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)
RUN_TAG = f"ma_tangle_matrix_{START}_{END}"


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _write_variant_md(
    summary: dict, equity_curve: list[dict], trades: list[dict]
) -> Path:
    """单变体回测报告 markdown(每轮跑完立即落盘)。"""
    vid = summary["id"]
    md_path = OUT_DIR / f"{RUN_TAG}_{vid}.md"

    # 取关键 equity 节点
    if equity_curve:
        first = equity_curve[0]
        last = equity_curve[-1]
        peak = max(equity_curve, key=lambda x: x["total_value"])
        trough_after_peak = min(
            (e for e in equity_curve if e["date"] >= peak["date"]),
            key=lambda x: x["total_value"],
            default=peak,
        )
    else:
        first = last = peak = trough_after_peak = {"date": "", "total_value": 0}

    # 交易统计:盈亏分布
    pnls = [t.get("pnl", 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    hold_days = [
        t.get("hold_days", 0) for t in trades if t.get("hold_days") is not None
    ]
    avg_hold = sum(hold_days) / len(hold_days) if hold_days else 0

    md = f"""# {vid} — {summary["note"]}

**运行区间**:{START} → {END}
**变体参数**:
- `sell_pe_pb_max` = {summary["sell_pe_pb_max"]}(0=关闭估值退出)
- `sell_below_ma`  = `{summary["sell_below_ma"]}`(none/ma10/ma20/ma30)
- `max_holdings`   = 20
- `buy_weeks`      = 8

## 核心指标

| 指标 | 数值 |
|---|---|
| **总收益** | **{_pct(summary["total_return"])}** |
| **年化收益** | **{_pct(summary["annualized_return"])}** |
| 最大回撤 | {_pct(summary["max_drawdown"])} |
| 夏普比率 | {summary["sharpe_ratio"]:.2f} |
| 胜率 | {_pct(summary["win_rate"])} |
| 盈亏比(profit factor) | {summary["profit_factor"]:.2f} |
| 平均盈利/单笔 | {_pct(summary["avg_win"])} |
| 平均亏损/单笔 | {_pct(summary["avg_loss"])} |
| 单边交易次数 | {summary["raw_trades"]} |
| Round-trip 笔数 | {summary["round_trips"]} |
| 日均换手率 | {_pct(summary["daily_turnover_rate"])} |
| 平均持有天数 | {avg_hold:.0f} 天 |
| 期末总市值 | {summary["final_equity"]:,.0f} |
| 回测耗时 | {summary["elapsed_sec"]} 秒 |

## 资金曲线关键点

| 节点 | 日期 | 总市值 |
|---|---|---|
| 起点 | {first.get("date", "")} | {first.get("total_value", 0):,.0f} |
| 高点 | {peak.get("date", "")} | {peak.get("total_value", 0):,.0f} |
| 高点后低点 | {trough_after_peak.get("date", "")} | {trough_after_peak.get("total_value", 0):,.0f} |
| 终点 | {last.get("date", "")} | {last.get("total_value", 0):,.0f} |

## 交易盈亏分布

- 盈利单数:{len(wins)}(累计 {sum(wins):,.0f})
- 亏损单数:{len(losses)}(累计 {sum(losses):,.0f})
- 最大单笔盈利:{max(pnls) if pnls else 0:,.0f}
- 最大单笔亏损:{min(pnls) if pnls else 0:,.0f}

## 是否达标

> 目标年化 ≥ 20%:**{"✅ 达标" if summary["annualized_return"] >= 0.20 else "❌ 未达标"}**(实际 {_pct(summary["annualized_return"])})
"""
    md_path.write_text(md, encoding="utf-8")
    return md_path


def _write_overview_md(summaries: list[dict]) -> Path:
    """全量汇总报告(每完成一轮都重写,全跑完后是最终版)。"""
    md_path = OUT_DIR / f"{RUN_TAG}_overview.md"
    ok = [s for s in summaries if "error" not in s]
    ok.sort(key=lambda s: s.get("annualized_return", 0), reverse=True)

    lines = [
        f"# MaTangleValueStrategy 卖出策略矩阵回测",
        "",
        f"**区间**:{START} → {END}",
        f"**变体数**:{len(VARIANTS)},已完成:{len(ok)}",
        f"**目标**:年化 ≥ 20%",
        "",
        "## 排行榜(按年化降序)",
        "",
        "| 排名 | ID | 备注 | PE\\*PB 退出 | MA 退出 | 总收益 | **年化** | 最大回撤 | 夏普 | 胜率 | round-trips | 达标 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ok, 1):
        ok_mark = "✅" if s.get("annualized_return", 0) >= 0.20 else "—"
        lines.append(
            f"| {i} | {s['id']} | {s['note']} | "
            f"{s['sell_pe_pb_max']} | `{s['sell_below_ma']}` | "
            f"{_pct(s['total_return'])} | **{_pct(s['annualized_return'])}** | "
            f"{_pct(s['max_drawdown'])} | {s['sharpe_ratio']:.2f} | "
            f"{_pct(s['win_rate'])} | {s['round_trips']} | {ok_mark} |"
        )

    failed = [s for s in summaries if "error" in s]
    if failed:
        lines += ["", "## 失败变体", ""]
        for s in failed:
            lines.append(f"- **{s['id']}**: {s['error']}")

    # 单变体详细报告链接
    if ok:
        lines += ["", "## 单变体详细报告", ""]
        for s in ok:
            lines.append(f"- [{s['id']} — {s['note']}]({RUN_TAG}_{s['id']}.md)")

    # 简单分析
    if ok:
        best = ok[0]
        lines += [
            "",
            "## 结论",
            "",
            f"**最优变体:{best['id']}({best['note']})**,年化 {_pct(best['annualized_return'])},"
            f"最大回撤 {_pct(best['max_drawdown'])}。",
        ]
        passing = [s for s in ok if s.get("annualized_return", 0) >= 0.20]
        if passing:
            lines.append(
                f"\n达成年化 ≥ 20% 的变体共 {len(passing)} 个:"
                + ", ".join(s["id"] for s in passing)
            )
        else:
            lines.append("\n**没有变体达成年化 ≥ 20% 目标**,需要进一步调参或换思路。")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def _load_bundle():
    log.info("加载 A 股 bundle...")
    t0 = time.time()
    bundle = data_cache.get_market("A")
    if bundle is None:
        bundle = data_cache._load_market_blocking("A")
    log.info(
        "bundle ready in %.1fs: stocks=%d valuation=%d financial=%d dividend=%d",
        time.time() - t0,
        len(bundle.stock_data),
        len(bundle.valuation_data),
        len(bundle.dividend_data),
        len(bundle.financial_data),
    )
    return bundle


def _run_variant(bundle, variant: dict) -> dict:
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info(
        "[%s] sliced: %d stocks, iter [%d, %d]",
        variant["id"],
        len(sliced.stock_data),
        sliced.iter_start_idx,
        sliced.iter_end_idx,
    )

    overrides = {
        "sell_pe_pb_max": variant["sell_pe_pb_max"],
        "sell_below_ma": variant["sell_below_ma"],
        "max_holdings": 20,
        "buy_weeks": 8,
    }
    strategy = MaTangleValueStrategy(param_overrides=overrides)

    log_dir = ROOT / "data" / "logs" / "matrix" / variant["id"]
    log_dir.mkdir(parents=True, exist_ok=True)

    last_pct = [-1]

    def on_progress(cur, total):
        if total <= 0:
            return
        pct = int(cur * 100 / total)
        if pct >= last_pct[0] + 10:
            log.info("  [%s] %d%% (%d/%d)", variant["id"], pct, cur, total)
            last_pct[0] = pct

    engine = BacktestEngine(
        strategy=strategy,
        stock_data=sliced.stock_data,
        valuation_data=sliced.valuation_data,
        dividend_data=sliced.dividend_data,
        financial_data=sliced.financial_data,
        weekly_data=sliced.weekly_data,
        monthly_data=sliced.monthly_data,
        iter_start=sliced.iter_start_idx,
        iter_end=sliced.iter_end_idx,
        on_progress=on_progress,
        log_dir=log_dir,
        enable_decision_log=False,  # 9 轮回测全开日志会爆磁盘
    )

    t0 = time.time()
    result = engine.run()
    elapsed = time.time() - t0

    metrics = result["metrics"]
    raw_trades = result.get("raw_trades", [])
    round_trips = result.get("trades", [])
    equity_curve = result.get("equity_curve", [])
    final_equity = equity_curve[-1]["total_value"] if equity_curve else 0

    summary = {
        "id": variant["id"],
        "note": variant["note"],
        "sell_pe_pb_max": variant["sell_pe_pb_max"],
        "sell_below_ma": variant["sell_below_ma"],
        "elapsed_sec": round(elapsed, 1),
        "final_equity": round(final_equity, 2),
        **metrics,
        "raw_trades": len(raw_trades),
        "round_trips": len(round_trips),
    }

    # 单变体 markdown 落盘(每轮即时产出)
    md_path = _write_variant_md(summary, equity_curve, round_trips)
    log.info("[%s] markdown -> %s", variant["id"], md_path.name)
    log.info(
        "[%s] DONE %.1fs total_return=%.2f%% annual=%.2f%% mdd=%.2f%% sharpe=%.2f trades=%d",
        variant["id"],
        elapsed,
        metrics["total_return"] * 100,
        metrics["annualized_return"] * 100,
        metrics["max_drawdown"] * 100,
        metrics["sharpe_ratio"],
        len(round_trips),
    )
    return summary


def main():
    bundle = _load_bundle()
    variants = [v for v in VARIANTS if SELECTED is None or v["id"] in SELECTED]
    log.info("将运行变体: %s", [v["id"] for v in variants])

    summaries: list[dict] = []
    out_file = OUT_DIR / f"{RUN_TAG}.json"

    for variant in variants:
        try:
            s = _run_variant(bundle, variant)
            summaries.append(s)
        except Exception as e:
            log.exception("[%s] FAILED: %s", variant["id"], e)
            summaries.append({"id": variant["id"], "error": str(e)})
        # 增量落盘:JSON + 实时刷新 overview 排行榜
        out_file.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
        ov_path = _write_overview_md(summaries)
        log.info("overview refreshed -> %s", ov_path.name)

    # ---------- 排版输出 ----------
    print("\n\n========== 矩阵回测结果 ==========")
    print(f"区间: {START} → {END}\n")
    fmt = "{id:>4} {note:<22} {tr:>10} {ann:>10} {mdd:>10} {sharpe:>8} {win:>8} {trips:>8}"
    print(
        fmt.format(
            id="ID",
            note="备注",
            tr="总收益",
            ann="年化",
            mdd="最大回撤",
            sharpe="夏普",
            win="胜率",
            trips="round-trips",
        )
    )
    print("-" * 100)
    ok_summaries = [s for s in summaries if "error" not in s]
    ok_summaries.sort(key=lambda s: s.get("annualized_return", 0), reverse=True)
    for s in ok_summaries:
        print(
            fmt.format(
                id=s["id"],
                note=s["note"][:22],
                tr=f"{s['total_return'] * 100:.2f}%",
                ann=f"{s['annualized_return'] * 100:.2f}%",
                mdd=f"{s['max_drawdown'] * 100:.2f}%",
                sharpe=f"{s['sharpe_ratio']:.2f}",
                win=f"{s['win_rate'] * 100:.1f}%",
                trips=str(s["round_trips"]),
            )
        )
    print(f"\n结果 JSON: {out_file}")


if __name__ == "__main__":
    main()
