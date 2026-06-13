"""Phase 4 — A 不回归 + HK 4960397f 重跑端到端验证。

目的:验证 Phase 1/2/3 重构(业务视图 + data_cache 切视图 + conservative 跨市退化)
- A 股:对照基线 25ee4d1f(R 阶段 3568→46,total_return 3.236,trades 195),不回归
- HK:对照 4960397f 旧版(R 阶段 1172→0,trades 0),修复后应有非零交易

使用 ConservativeRoughStrategy 默认参数(与原任务一致):
    min_dividend_years=5, r_threshold_pct=5.2, max_goodwill_ratio=0.3,
    max_roe_decline=0.3, use_trap_rating_soft=True, max_per_stock_pct=0.2,
    buy_weeks=4, max_holdings=15, frequency=monthly

时间区间:2017-01-01 → 2026-05-28(与基线对齐)。

输出:logs/phase4/{A,HK}/ 下 flow.jsonl + summary.json,与基线 logs/backtest/{25ee4d1f,4960397f}/flow.jsonl 对照
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
log = logging.getLogger("phase4")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.deployed.conservative_rough_strategy import ConservativeRoughStrategy

START = "2017-01-01"
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


def run_market(market: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("=== %s 市场 — 加载 bundle ===", market)
    t0 = time.time()
    bundle = data_cache.get_market(market)
    if bundle is None:
        bundle = data_cache._load_market_blocking(market)
    log.info(
        "%s bundle %.1fs: %d stocks, %d financial, %d income, %d balance, %d cashflow, %d valuation, %d dividend",
        market,
        time.time() - t0,
        len(bundle.stock_data),
        len(bundle.financial_data),
        len(getattr(bundle, "income_data", {}) or {}),
        len(getattr(bundle, "balance_data", {}) or {}),
        len(getattr(bundle, "cashflow_data", {}) or {}),
        len(bundle.valuation_data),
        len(bundle.dividend_data),
    )

    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info(
        "%s sliced: %d stocks, iter [%d, %d]",
        market,
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
            log.info("  [%s] %d%% (%d/%d) %s", market, pct, cur, total, phase)
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
        "market": market,
        "elapsed_sec": round(elapsed, 1),
        "total_return": metrics.get("total_return"),
        "annual_return": metrics.get("annual_return"),
        "max_drawdown": metrics.get("max_drawdown"),
        "round_trips": len(trades),
        "raw_trades": len(raw_trades),
        "params": PARAMS,
        "range": [START, END],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("=== %s 完成 %.1fs: %s ===", market, elapsed, summary)
    return summary


def main():
    out_root = ROOT / "logs" / "phase4"
    a = run_market("A", out_root / "A")
    hk = run_market("HK", out_root / "HK")
    final = {"A": a, "HK": hk}
    (out_root / "summary.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("=== Phase 4 ALL DONE ===")
    log.info("A baseline 25ee4d1f: trades=195, total_return=3.236")
    log.info("HK baseline 4960397f: trades=0, total_return=0")
    log.info("New A: trades=%d, total_return=%s", a["round_trips"], a["total_return"])
    log.info(
        "New HK: trades=%d, total_return=%s", hk["round_trips"], hk["total_return"]
    )


if __name__ == "__main__":
    main()
