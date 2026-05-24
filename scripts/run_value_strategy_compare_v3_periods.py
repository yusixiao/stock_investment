"""ValueFactorBreakoutStrategy v3 区间扫描:V0 默认参数在不同回测期表现。

v1/v2 在 2010-2026 全期间最高 ~3% 年化,远低于 10% 目标。
猜想:2010-2014 早期数据稀疏 + 2015 股灾扰动 + 2024 熊市拖累。
本脚本固定 V0 参数,只换区间,看是否存在能达到 10% 的稳定子区间。

测试区间:
- P0: 2010-01-01 → 2026-05-23(基线,已知 2.96%)
- P1: 2015-01-01 → 2026-05-23
- P2: 2018-01-01 → 2026-05-23
- P3: 2020-01-01 → 2026-05-23
- P4: 2010-01-01 → 2021-12-31(避开 2022-2024 熊市)
- P5: 2015-01-01 → 2021-12-31(牛市为主)
- P6: 2019-01-01 → 2023-12-31(2019-2021 大牛后回吐)
- P7: 2014-01-01 → 2018-12-31(2014-2015 牛市 + 2016-2018 调整)
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
log = logging.getLogger("vfb_v3")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.examples.value_factor_breakout_strategy import (
    ValueFactorBreakoutStrategy,
)


V0_PARAMS = {
    "min_dividend_years": 5,
    "pe_pb_min": 0.0,
    "pe_pb_max": 22.0,
    "min_roe": 10.0,
    "ma_window": 0,
    "buy_weeks": 4,
    "max_holdings": 15,
    "sell_pe_pb_max": 0.0,
    "sell_below_ma": "none",
}

PERIODS = [
    ("P0", "2010-01-01", "2026-05-23", "全期基线"),
    ("P1", "2015-01-01", "2026-05-23", "2015 起"),
    ("P2", "2018-01-01", "2026-05-23", "2018 起"),
    ("P3", "2020-01-01", "2026-05-23", "2020 起"),
    ("P4", "2010-01-01", "2021-12-31", "避开 2022-2024 熊"),
    ("P5", "2015-01-01", "2021-12-31", "牛市为主"),
    ("P6", "2019-01-01", "2023-12-31", "牛后回吐"),
    ("P7", "2014-01-01", "2018-12-31", "牛后调整"),
]

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)
RUN_TAG = "value_compare_v3_periods"


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _compute_cash_metrics(equity_curve):
    if not equity_curve:
        return {"avg_cash_ratio": 0.0, "fully_invested_days_pct": 0.0}
    ratios = [
        pt["cash"] / pt["total_value"]
        for pt in equity_curve
        if pt.get("total_value", 0) > 0
    ]
    if not ratios:
        return {"avg_cash_ratio": 0.0, "fully_invested_days_pct": 0.0}
    return {
        "avg_cash_ratio": sum(ratios) / len(ratios),
        "fully_invested_days_pct": sum(1 for r in ratios if r < 0.1) / len(ratios),
    }


def _load_bundle():
    log.info("加载全市场数据 bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A")
    if bundle is None:
        bundle = data_cache._load_market_blocking("A")
    log.info("bundle 加载完成 %.1fs", time.time() - t0)
    return bundle


def _run_period(bundle, pid, start, end, note):
    sliced = data_cache.slice_bundle(bundle, None, start, end)
    strategy = ValueFactorBreakoutStrategy(param_overrides=V0_PARAMS)

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
        enable_decision_log=False,
    )

    t0 = time.time()
    result = engine.run()
    elapsed = time.time() - t0

    metrics = result["metrics"]
    raw_trades = result.get("raw_trades", [])
    cash = _compute_cash_metrics(result.get("equity_curve", []))

    summary = {
        "id": pid,
        "note": note,
        "start": start,
        "end": end,
        "elapsed_sec": round(elapsed, 1),
        **metrics,
        "raw_trades": len(raw_trades),
        **cash,
    }
    log.info(
        "[%s %s→%s] DONE %.1fs annual=%.2f%% mdd=%.2f%% trades=%d",
        pid,
        start,
        end,
        elapsed,
        metrics["annualized_return"] * 100,
        metrics["max_drawdown"] * 100,
        len(raw_trades),
    )
    return summary


def _write_overview(summaries):
    md_path = OUT_DIR / f"{RUN_TAG}_overview.md"
    ok = [s for s in summaries if "annualized_return" in s]
    ok_sorted = sorted(ok, key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        "# ValueFactorBreakoutStrategy v3 区间扫描",
        "",
        "**固定参数**:V0 (min_div=5, pe_pb≤22, roe≥10, max_hold=15, buy_weeks=4, 无择时)",
        "**目的**:看是否存在能达 10% 的稳定子区间(全期 2.96%,目标 ≥10%)",
        f"**区间数**:{len(PERIODS)},已完成:{len(ok)}",
        "",
        "## 排行榜",
        "",
        "| 排名 | ID | 区间 | 备注 | 年化 | 最大回撤 | 笔数 | 现金占比 | 满仓占比 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ok_sorted, 1):
        lines.append(
            f"| {i} | {s['id']} | {s['start']}→{s['end']} | {s['note']} | "
            f"**{_pct(s['annualized_return'])}** | {_pct(s['max_drawdown'])} | "
            f"{s['raw_trades']} | {_pct(s['avg_cash_ratio'])} | "
            f"{_pct(s['fully_invested_days_pct'])} |"
        )
    md_path.write_text("\n".join(lines))
    return md_path


def main():
    bundle = _load_bundle()
    summaries = []
    out_file = OUT_DIR / f"{RUN_TAG}.json"

    for pid, start, end, note in PERIODS:
        try:
            s = _run_period(bundle, pid, start, end, note)
            summaries.append(s)
        except Exception as e:
            log.exception("[%s] FAILED: %s", pid, e)
            summaries.append({"id": pid, "error": str(e)})
        out_file.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
        _write_overview(summaries)

    print(f"\n结果: {out_file}")


if __name__ == "__main__":
    main()
