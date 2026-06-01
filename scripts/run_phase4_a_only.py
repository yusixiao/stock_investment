"""Phase 4 — A 股 only,用 baseline cbd4870 的 conservative 文件验证 195 trades 是否可复现。"""

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
log = logging.getLogger("phase4_a")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.examples.conservative_rough_strategy import ConservativeRoughStrategy

START = "2010-01-01"
END = "2026-05-28"
PARAMS = {
    "min_dividend_years": 5,
    "r_threshold_pct": 5.2,
    "max_goodwill_ratio": 0.3,
    "max_roe_decline": 0.3,
    "use_trap_rating_soft": True,
    "max_per_stock_pct": 0.2,
    "buy_weeks": 4,
    "max_holdings": 15,
}


def main():
    out_dir = ROOT / "logs" / "phase4_baseline_replay" / "A"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== A 加载 bundle ===")
    t0 = time.time()
    bundle = data_cache.get_market("A")
    if bundle is None:
        bundle = data_cache._load_market_blocking("A")
    log.info("bundle %.1fs: %d stocks", time.time() - t0, len(bundle.stock_data))

    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info(
        "sliced: %d stocks, iter [%d, %d]",
        len(sliced.stock_data),
        sliced.iter_start_idx,
        sliced.iter_end_idx,
    )

    strategy = ConservativeRoughStrategy(param_overrides=PARAMS)

    last_pct = [-1]

    def on_progress(cur, total, phase=""):
        if total <= 0:
            return
        pct = int(cur * 100 / total)
        if pct >= last_pct[0] + 10:
            log.info("  %d%% (%d/%d) %s", pct, cur, total, phase)
            last_pct[0] = pct

    engine = BacktestEngine(
        strategy=strategy,
        stock_data=sliced.stock_data,
        valuation_data=sliced.valuation_data,
        dividend_data=sliced.dividend_data,
        financial_data=sliced.financial_data,
        balance_data=getattr(sliced, "balance_data", None),
        cashflow_data=getattr(sliced, "cashflow_data", None),
        income_data=getattr(sliced, "income_data", None),
        weekly_data=getattr(sliced, "weekly_data", None),
        monthly_data=getattr(sliced, "monthly_data", None),
        iter_start=sliced.iter_start_idx,
        iter_end=sliced.iter_end_idx,
        on_progress=on_progress,
        enable_decision_log=True,
        log_dir=out_dir,
    )

    t0 = time.time()
    result = engine.run()
    elapsed = time.time() - t0

    metrics = result.get("metrics", {})
    trades = result.get("trades", [])
    raw_trades = result.get("raw_trades", [])
    summary = {
        "market": "A",
        "elapsed_sec": round(elapsed, 1),
        "total_return": metrics.get("total_return"),
        "annual_return": metrics.get("annual_return"),
        "max_drawdown": metrics.get("max_drawdown"),
        "round_trips": len(trades),
        "raw_trades": len(raw_trades),
        "params": PARAMS,
        "range": [START, END],
        "note": "baseline cbd4870 conservative files + new data path (business view + sliced.balance/cashflow/income)",
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("=== DONE %.1fs: %s ===", elapsed, summary)
    log.info("baseline 25ee4d1f: trades=195, total_return=3.236")
    log.info(
        "replay: trades=%d, total_return=%s", len(trades), metrics.get("total_return")
    )


if __name__ == "__main__":
    main()
