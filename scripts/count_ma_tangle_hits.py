"""统计 MaTangleValueStrategy 在指定区间内命中的股票数量。

只跑选股(run_scan),不考虑买入/卖出。

用法:
    python scripts/count_ma_tangle_hits.py [START] [END]
    例:python scripts/count_ma_tangle_hits.py 2017-01-01 2026-05-24
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
log = logging.getLogger("count_hits")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy

START = sys.argv[1] if len(sys.argv) > 1 else "2017-01-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-05-24"

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)


def main():
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

    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info(
        "sliced: %d stocks, iter [%d, %d]",
        len(sliced.stock_data),
        sliced.iter_start_idx,
        sliced.iter_end_idx,
    )

    strategy = MaTangleValueStrategy()

    last_pct = [-1]

    def on_progress(cur, total):
        if total <= 0:
            return
        pct = int(cur * 100 / total)
        if pct >= last_pct[0] + 5:
            log.info("  scan %d%% (%d/%d)", pct, cur, total)
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
    )

    log.info("开始 run_scan...")
    t0 = time.time()
    result = engine.run_scan()
    elapsed = time.time() - t0
    log.info("run_scan done in %.1fs", elapsed)

    events = result["events"]
    all_count = result["all_symbols_count"]
    unique_hit_count = len(events)

    # 每只命中股票的命中次数
    hits_per_symbol = {sym: len(evts) for sym, evts in events.items()}
    total_hit_events = sum(hits_per_symbol.values())

    # 按命中次数排序的 top 30
    top = sorted(hits_per_symbol.items(), key=lambda x: -x[1])[:30]

    print("\n" + "=" * 60)
    print(f"MaTangleValueStrategy 选股扫描结果")
    print(f"区间: {START} → {END}")
    print(f"策略频率: {strategy.frequency}")
    print("=" * 60)
    print(f"全市场股票数:        {all_count}")
    print(f"至少命中一次的股票数: {unique_hit_count}")
    print(f"命中事件总数:        {total_hit_events}")
    print(f"覆盖率:              {unique_hit_count / all_count * 100:.2f}%")
    print(f"耗时:                {elapsed:.1f}s")
    print(f"\nTop 30 命中次数最多的股票:")
    for i, (sym, cnt) in enumerate(top, 1):
        print(f"  {i:2d}. {sym}  命中 {cnt} 次")

    # 落盘
    out = {
        "start": START,
        "end": END,
        "all_symbols_count": all_count,
        "unique_hit_count": unique_hit_count,
        "total_hit_events": total_hit_events,
        "hits_per_symbol": hits_per_symbol,
        "events": {
            sym: [(d, factors) for d, factors in evts] for sym, evts in events.items()
        },
    }
    out_path = OUT_DIR / f"ma_tangle_hits_{START}_{END}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log.info("结果落盘 -> %s", out_path)


if __name__ == "__main__":
    main()
