"""MaTangleValueStrategy 诊断式 baseline 回测。

目的:定位现有矩阵年化偏低的根因 —— 是信号问题还是资金管理问题?

诊断变体(全部关闭 sell hook,永久持有):
- D0  原版默认            : pe_pb_max=22, min_div=5, min_roe=10, buy_weeks=8, max_hold=20  (= 矩阵 V0)
- D1  放开持仓上限         : 同 D0,但 max_holdings=999, buy_weeks=1   (诊断分仓堵塞)
- D2  D1 + 放宽估值        : pe_pb_max=100                            (诊断估值过滤过严)
- D3  D2 + 放宽分红/ROE    : min_div=0, min_roe=0                     (诊断基本面过滤过严)
- D4  纯信号               : D3 基础上 pe_pb_max=99999                (纯月线 tangle 信号)

输出:每变体年化、最大回撤、买入笔数、平均现金占比、资金利用率。
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
log = logging.getLogger("diag")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy

VARIANTS = [
    {
        "id": "D0",
        "note": "原版默认(=矩阵V0)",
        "params": {
            "min_dividend_years": 5,
            "pe_pb_max": 22.0,
            "min_roe": 10.0,
            "buy_weeks": 8,
            "max_holdings": 20,
            "sell_pe_pb_max": 0.0,
            "sell_below_ma": "none",
        },
    },
    {
        "id": "D1",
        "note": "放开仓位+1周满买",
        "params": {
            "min_dividend_years": 5,
            "pe_pb_max": 22.0,
            "min_roe": 10.0,
            "buy_weeks": 1,
            "max_holdings": 999,
            "sell_pe_pb_max": 0.0,
            "sell_below_ma": "none",
        },
    },
    {
        "id": "D2",
        "note": "D1+放宽估值(PE*PB<100)",
        "params": {
            "min_dividend_years": 5,
            "pe_pb_max": 100.0,
            "min_roe": 10.0,
            "buy_weeks": 1,
            "max_holdings": 999,
            "sell_pe_pb_max": 0.0,
            "sell_below_ma": "none",
        },
    },
    {
        "id": "D3",
        "note": "D2+放宽分红/ROE",
        "params": {
            "min_dividend_years": 0,
            "pe_pb_max": 100.0,
            "min_roe": 0.0,
            "buy_weeks": 1,
            "max_holdings": 999,
            "sell_pe_pb_max": 0.0,
            "sell_below_ma": "none",
        },
    },
    {
        "id": "D4",
        "note": "纯月线tangle信号",
        "params": {
            "min_dividend_years": 0,
            "pe_pb_max": 99999.0,
            "min_roe": 0.0,
            "buy_weeks": 1,
            "max_holdings": 999,
            "sell_pe_pb_max": 0.0,
            "sell_below_ma": "none",
        },
    },
]

START = sys.argv[1] if len(sys.argv) > 1 else "2010-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-05-23"
SELECTED = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)
RUN_TAG = f"ma_tangle_diag_{START}_{END}"


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _compute_cash_metrics(equity_curve: list[dict]) -> dict:
    """从 equity_curve 算资金利用率指标。"""
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
    median = ratios[n // 2]
    avg = sum(ratios) / n
    fully_invested = sum(1 for r in ratios if r < 0.1) / n  # 现金<10% 算满仓
    return {
        "avg_cash_ratio": avg,
        "median_cash_ratio": median,
        "fully_invested_days_pct": fully_invested,
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

    strategy = MaTangleValueStrategy(param_overrides=variant["params"])

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
        "[%s] DONE %.1fs annual=%.2f%% mdd=%.2f%% trades=%d cash_avg=%.1f%% fully_invested=%.1f%%",
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
        f"# MaTangle 诊断式 baseline 回测",
        f"",
        f"**区间**:{START} → {END}",
        f"**目的**:定位现有矩阵年化偏低的根因",
        f"**变体数**:{len(VARIANTS)},已完成:{len(ok)}",
        f"",
        f"## 排行榜",
        f"",
        f"| 排名 | ID | 备注 | 年化 | 最大回撤 | 买入笔数 | 平均现金占比 | 满仓天数占比 |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ok_sorted, 1):
        lines.append(
            f"| {i} | {s['id']} | {s['note']} | **{_pct(s['annualized_return'])}** | "
            f"{_pct(s['max_drawdown'])} | {s['raw_trades']} | "
            f"{_pct(s['avg_cash_ratio'])} | {_pct(s['fully_invested_days_pct'])} |"
        )
    lines.append("")
    lines.append("## 诊断解读")
    lines.append("")
    lines.append("- `平均现金占比` 越高 → 资金闲置越严重 → 优化方向是资金管理")
    lines.append("- `满仓天数占比` 越低 → 大部分时间没投出去")
    lines.append("- 若 D4(纯信号)年化仍 <10% → 信号本身价值有限,需换思路")
    lines.append(
        "- 若 D1(放开仓位)显著 > D0 → 原矩阵的 buy_weeks=8 + max_holdings=20 是主要瓶颈"
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
