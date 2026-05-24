"""ValueFactorBreakoutStrategy v2 扩展参数矩阵。

v1 结论(2026-05-23 凌晨):
- V0(无择时)= 2.96%(最佳),V1(close>MA20)= 0.79%(择时反而负 alpha)
- 最大回撤 80%+,价值因子单兵作战不足以达 10% 目标

v2 假设方向(锚定 V0,聚焦 V0 之上的参数调整):
- H1: 集中持仓 → max_holdings ∈ {3, 5}(top-N 优于平均铺开)
- H2: 估值池宽度 → pe_pb_max ∈ {15, 33}(宽窄两侧探边界)
- H3: 精选门槛 → min_div=10, min_roe=15(高质量小池)
- H4: 卖出 hook → sell_pe_pb_max=44 / sell_below_ma=ma10(止盈/止损)
- H5: 组合精选 → 集中+放宽+高 ROE

注:全部基于 V0(ma_window=0,无择时),保持市值加权分配。
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
log = logging.getLogger("vfb_v2")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.examples.value_factor_breakout_strategy import (
    ValueFactorBreakoutStrategy,
)


def _v0(**overrides):
    """V0 基线(无择时,buy_weeks=4,max_holdings=15,pe_pb_max=22)。"""
    base = {
        "min_dividend_years": 5,
        "pe_pb_min": 0.0,
        "pe_pb_max": 22.0,
        "min_roe": 10.0,
        "ma_window": 0,  # 关闭择时
        "buy_weeks": 4,
        "max_holdings": 15,
        "sell_pe_pb_max": 0.0,
        "sell_below_ma": "none",
    }
    base.update(overrides)
    return base


VARIANTS = [
    {"id": "V8", "note": "集中持仓 top5", "params": _v0(max_holdings=5)},
    {"id": "V9", "note": "超集中持仓 top3", "params": _v0(max_holdings=3)},
    {"id": "V10", "note": "放宽估值池 pe_pb≤33", "params": _v0(pe_pb_max=33.0)},
    {"id": "V11", "note": "收紧估值池 pe_pb≤15", "params": _v0(pe_pb_max=15.0)},
    {
        "id": "V12",
        "note": "双精选 div≥10+roe≥15",
        "params": _v0(min_dividend_years=10, min_roe=15.0),
    },
    {
        "id": "V13",
        "note": "组合精选 top5+pe33+roe15",
        "params": _v0(max_holdings=5, pe_pb_max=33.0, min_roe=15.0),
    },
    {"id": "V14", "note": "止盈 sell_pe_pb_max=44", "params": _v0(sell_pe_pb_max=44.0)},
    {
        "id": "V15",
        "note": "止损 sell_below_ma=ma10",
        "params": _v0(sell_below_ma="ma10"),
    },
]

# v1 基线引用(已知)
V0_REF = {
    "id": "V0(参考)",
    "note": "v1 V0 基线",
    "annualized_return": 0.0296,
}
D0_REF = {
    "id": "D0(参考)",
    "note": "MaTangleValueStrategy 默认",
    "annualized_return": 0.0233,
}

START = sys.argv[1] if len(sys.argv) > 1 else "2010-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-05-23"
SELECTED = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)
RUN_TAG = f"value_compare_v2_{START}_{END}"


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _compute_cash_metrics(equity_curve):
    if not equity_curve:
        return {
            "avg_cash_ratio": 0.0,
            "median_cash_ratio": 0.0,
            "fully_invested_days_pct": 0.0,
        }
    ratios = [
        pt["cash"] / pt["total_value"]
        for pt in equity_curve
        if pt.get("total_value", 0) > 0
    ]
    if not ratios:
        return {
            "avg_cash_ratio": 0.0,
            "median_cash_ratio": 0.0,
            "fully_invested_days_pct": 0.0,
        }
    ratios.sort()
    n = len(ratios)
    return {
        "avg_cash_ratio": sum(ratios) / n,
        "median_cash_ratio": ratios[n // 2],
        "fully_invested_days_pct": sum(1 for r in ratios if r < 0.1) / n,
    }


def _load_bundle():
    log.info("加载全市场数据 bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A")
    if bundle is None:
        bundle = data_cache._load_market_blocking("A")
    log.info("bundle 加载完成 %.1fs: %d 标的", time.time() - t0, len(bundle.stock_data))
    return bundle


def _run_variant(bundle, variant):
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    strategy = ValueFactorBreakoutStrategy(param_overrides=variant["params"])

    last_pct = [-1]

    def on_progress(cur, total):
        if total <= 0:
            return
        pct = int(cur * 100 / total)
        if pct >= last_pct[0] + 25:
            log.info("  [%s] %d%%", variant["id"], pct)
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
        enable_decision_log=False,
    )

    t0 = time.time()
    result = engine.run()
    elapsed = time.time() - t0

    metrics = result["metrics"]
    raw_trades = result.get("raw_trades", [])
    round_trips = result.get("trades", [])
    equity_curve = result.get("equity_curve", [])
    cash_metrics = _compute_cash_metrics(equity_curve)

    summary = {
        "id": variant["id"],
        "note": variant["note"],
        "params": variant["params"],
        "elapsed_sec": round(elapsed, 1),
        **metrics,
        "raw_trades": len(raw_trades),
        "round_trips": len(round_trips),
        **cash_metrics,
    }
    log.info(
        "[%s] DONE %.1fs annual=%.2f%% mdd=%.2f%% trades=%d cash=%.1f%%",
        variant["id"],
        elapsed,
        metrics["annualized_return"] * 100,
        metrics["max_drawdown"] * 100,
        len(raw_trades),
        cash_metrics["avg_cash_ratio"] * 100,
    )
    return summary


def _write_overview(summaries):
    md_path = OUT_DIR / f"{RUN_TAG}_overview.md"
    ok = [s for s in summaries if "annualized_return" in s]
    ok_sorted = sorted(ok, key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        "# ValueFactorBreakoutStrategy v2 扩展参数矩阵",
        "",
        f"**区间**:{START} → {END}",
        "**v1 结论**:V0(无择时,2.96%)是局部最优,close>MA20 择时是负 alpha。",
        "**v2 假设**:在 V0 之上做集中持仓 / 估值池 / 精选门槛 / 卖出 hook 单维度扫描。",
        f"**变体数**:{len(VARIANTS)},已完成:{len(ok)}",
        "",
        "## 排行榜",
        "",
        "| 排名 | ID | 备注 | 年化 | 最大回撤 | 笔数 | 现金占比 | 满仓占比 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ok_sorted, 1):
        lines.append(
            f"| {i} | {s['id']} | {s['note']} | **{_pct(s['annualized_return'])}** | "
            f"{_pct(s['max_drawdown'])} | {s['raw_trades']} | "
            f"{_pct(s['avg_cash_ratio'])} | {_pct(s['fully_invested_days_pct'])} |"
        )
    lines.append(
        f"| - | {V0_REF['id']} | {V0_REF['note']} | "
        f"{_pct(V0_REF['annualized_return'])} | - | - | - | - |"
    )
    lines.append(
        f"| - | {D0_REF['id']} | {D0_REF['note']} | "
        f"{_pct(D0_REF['annualized_return'])} | - | - | - | - |"
    )
    lines.append("")
    lines.append("## 解读")
    lines.append("")
    lines.append("- 集中持仓(V8/V9):top-N 是否优于 top-15 平铺?")
    lines.append("- 估值池宽窄(V10/V11):pe_pb_max ∈ {15, 22, 33}")
    lines.append("- 精选门槛(V12):div≥10+roe≥15 是否带来质量溢价?")
    lines.append("- 组合精选(V13):多维叠加是否突破 V0 上限?")
    lines.append("- 卖出 hook(V14/V15):止盈/止损是否提升 Sharpe?")
    lines.append(
        "- **目标 ≥10% 年化**;若全失败则需引入新 alpha 维度(动量/小市值/区间筛选)"
    )
    md_path.write_text("\n".join(lines))
    return md_path


def main():
    bundle = _load_bundle()
    variants = [v for v in VARIANTS if SELECTED is None or v["id"] in SELECTED]
    log.info("将运行变体: %s", [v["id"] for v in variants])

    summaries = []
    out_file = OUT_DIR / f"{RUN_TAG}.json"

    for variant in variants:
        try:
            s = _run_variant(bundle, variant)
            summaries.append(s)
        except Exception as e:
            log.exception("[%s] FAILED: %s", variant["id"], e)
            summaries.append({"id": variant["id"], "error": str(e)})
        out_file.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
        _write_overview(summaries)

    print(f"\n结果: {out_file}")


if __name__ == "__main__":
    main()
