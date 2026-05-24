"""ValueFactorBreakoutStrategy 8 变体对比回测。

设计参考 ma_tangle 诊断报告(2026-05-23):月线 tangle 信号实证负 alpha,
真正 alpha 来源是价值三因子。本脚本系统对比新策略的 8 种配置,定位:
- 简单 close>MA20 择时 vs 无择时(V0 vs V1)是否有正向贡献
- buy_weeks ∈ {1, 2, 4, 8} 哪个分批节奏最优
- sell hooks(PE*PB 退出 / MA 跌破退出)是否提升风险调整后收益

D0(MaTangleValueStrategy 默认,2.33% 年化)作为外部基线引用,
overview 表末尾追加 D0 行便于对照。

变体清单:
- V0  仅价值三因子(无择时)         : pe_pb=22, div=5, roe=10, buy_weeks=4, max=15, ma_window=0
- V1  V0 + close>MA20 + buy_weeks=4  : 主推荐
- V2  V1 但 buy_weeks=1
- V3  V1 但 buy_weeks=2
- V4  V1 但 buy_weeks=8(对齐 D0 节奏)
- V5  V1 + sell_below_ma=ma20
- V6  V1 + sell_pe_pb_max=33
- V7  V1 + 双 sell hooks(V5+V6)

仓位分配:全部使用市值加权(与 D0 一致,公平对比)
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
log = logging.getLogger("vfb_cmp")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.examples.value_factor_breakout_strategy import (
    ValueFactorBreakoutStrategy,
)


# 通用基线参数(V1)
def _base(buy_weeks=4, ma_window=20, sell_pe_pb_max=0.0, sell_below_ma="none"):
    return {
        "min_dividend_years": 5,
        "pe_pb_min": 0.0,
        "pe_pb_max": 22.0,
        "min_roe": 10.0,
        "ma_window": ma_window,
        "buy_weeks": buy_weeks,
        "max_holdings": 15,
        "sell_pe_pb_max": sell_pe_pb_max,
        "sell_below_ma": sell_below_ma,
    }


VARIANTS = [
    {
        "id": "V0",
        "note": "仅价值三因子(无择时)",
        "params": _base(buy_weeks=4, ma_window=0),
    },
    {
        "id": "V1",
        "note": "V0+close>MA20+buy_weeks=4(主推荐)",
        "params": _base(buy_weeks=4, ma_window=20),
    },
    {
        "id": "V2",
        "note": "V1 但 buy_weeks=1",
        "params": _base(buy_weeks=1, ma_window=20),
    },
    {
        "id": "V3",
        "note": "V1 但 buy_weeks=2",
        "params": _base(buy_weeks=2, ma_window=20),
    },
    {
        "id": "V4",
        "note": "V1 但 buy_weeks=8(对齐 D0)",
        "params": _base(buy_weeks=8, ma_window=20),
    },
    {
        "id": "V5",
        "note": "V1 + sell_below_ma=ma20",
        "params": _base(buy_weeks=4, ma_window=20, sell_below_ma="ma20"),
    },
    {
        "id": "V6",
        "note": "V1 + sell_pe_pb_max=33",
        "params": _base(buy_weeks=4, ma_window=20, sell_pe_pb_max=33.0),
    },
    {
        "id": "V7",
        "note": "V1 + 双 sell hooks(V5+V6)",
        "params": _base(
            buy_weeks=4, ma_window=20, sell_pe_pb_max=33.0, sell_below_ma="ma20"
        ),
    },
]

# D0 基线引用(来自 ma_tangle_diag overview,不参与本脚本运行)
D0_REF = {
    "id": "D0(参考)",
    "note": "MaTangleValueStrategy 默认(诊断报告引用值)",
    "annualized_return": 0.0233,
    "max_drawdown": None,
    "raw_trades": None,
    "avg_cash_ratio": None,
    "fully_invested_days_pct": None,
}

START = sys.argv[1] if len(sys.argv) > 1 else "2010-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-05-23"
SELECTED = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)
RUN_TAG = f"value_compare_{START}_{END}"


def _pct(x) -> str:
    if x is None:
        return "-"
    return f"{x * 100:.2f}%"


def _compute_cash_metrics(equity_curve: list[dict]) -> dict:
    if not equity_curve:
        return {
            "avg_cash_ratio": 0.0,
            "median_cash_ratio": 0.0,
            "fully_invested_days_pct": 0.0,
        }
    ratios = []
    for pt in equity_curve:
        total = pt.get("total_value", 0)
        cash = pt.get("cash", 0)
        if total > 0:
            ratios.append(cash / total)
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
    log.info(
        "bundle 加载完成 %.1fs: %d 标的, %d valuation, %d dividend, %d financial",
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

    strategy = ValueFactorBreakoutStrategy(param_overrides=variant["params"])

    last_pct = [-1]

    def on_progress(cur, total):
        if total <= 0:
            return
        pct = int(cur * 100 / total)
        if pct >= last_pct[0] + 20:
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
        "[%s] DONE %.1fs annual=%.2f%% mdd=%.2f%% trades=%d cash_avg=%.1f%% fully=%.1f%%",
        variant["id"],
        elapsed,
        metrics["annualized_return"] * 100,
        metrics["max_drawdown"] * 100,
        len(raw_trades),
        cash_metrics["avg_cash_ratio"] * 100,
        cash_metrics["fully_invested_days_pct"] * 100,
    )
    return summary


def _write_overview(summaries: list[dict]) -> Path:
    md_path = OUT_DIR / f"{RUN_TAG}_overview.md"
    ok = [s for s in summaries if "annualized_return" in s]
    ok_sorted = sorted(ok, key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        "# ValueFactorBreakoutStrategy 8 变体对比回测",
        "",
        f"**区间**:{START} → {END}",
        "**目的**:在 ma_tangle 诊断结论(月线 tangle 负 alpha,价值因子才是来源)基础上,",
        "评估「极简 close>MA20 择时 + 价值三因子」组合,系统对比择时/分批/卖出 hook 影响。",
        f"**变体数**:{len(VARIANTS)},已完成:{len(ok)}",
        "",
        "## 排行榜",
        "",
        "| 排名 | ID | 备注 | 年化 | 最大回撤 | 买入笔数 | 平均现金占比 | 满仓天数占比 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ok_sorted, 1):
        lines.append(
            f"| {i} | {s['id']} | {s['note']} | **{_pct(s['annualized_return'])}** | "
            f"{_pct(s['max_drawdown'])} | {s['raw_trades']} | "
            f"{_pct(s['avg_cash_ratio'])} | {_pct(s['fully_invested_days_pct'])} |"
        )
    # 追加 D0 基线引用行(不排序,固定置底)
    lines.append(
        f"| - | {D0_REF['id']} | {D0_REF['note']} | "
        f"{_pct(D0_REF['annualized_return'])} | - | - | - | - |"
    )
    lines.append("")
    lines.append("## 解读维度")
    lines.append("")
    lines.append("- **V0 vs V1**:close>MA20 择时是否有正向贡献?")
    lines.append("- **V1 vs V2/V3/V4**:buy_weeks ∈ {1,2,4,8} 哪个最优?")
    lines.append("- **V1 vs V5/V6/V7**:卖出 hook 是否能提升风险调整后收益?")
    lines.append(
        "- **vs D0 (2.33%)**:新策略是否跑赢被实证负 alpha 的旧 tangle 信号策略?"
    )
    lines.append(
        "- 满仓天数占比偏低 → 价值池窗口期常缺标的;现金占比偏高 → 可能是分批节奏太慢"
    )
    md_path.write_text("\n".join(lines))
    return md_path


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
        out_file.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
        ov = _write_overview(summaries)
        log.info("overview -> %s", ov.name)

    print(f"\n结果: {out_file}")


if __name__ == "__main__":
    main()
