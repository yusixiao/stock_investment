#!/usr/bin/env python3
"""slow_growers 冠军·报告头条值精确复现验证(修复 INDUSTRY_NAME 后)。

背景
----
单型研究报告 slow_growers 冠军**头条值** = 全期 **2010-06-01 → 2026-06-01**:
  CAGR 14.28% / 总收益 745.72% / MaxDD 23.85% / 139 笔
报告另注 2010-01-01 口径 = 13.90%(其余同,因 rebalance_months=[6] 首个调仓均落在
2010-06,交易/回撤一致,仅 2010-01 起点多约 5 个月空仓摊薄 years → CAGR 略低)。

此前 INDUSTRY_NAME 数据回归(明细报表不含该字段)致冠军 max_per_sector=2 桶塌陷,
full(2010-01)重跑塌到 9.94%/31 笔。修复 fetch_balance 补回 INDUSTRY_NAME + 全量重抽后,
verify_sg_maxsector 已复现 2010-01 口径 13.90%/139/DD23.85。本脚本进一步在**报告头条
起点 2010-06-01** 上精确复现 **14.28%**,作为修复正确性的终局判据。

判据
----
- 2010-06-01 → CAGR ≈ 14.28% / total ≈ 745.72% / MaxDD ≈ 23.85% / trades = 139 → 精确复现;
- 2010-01-01 → CAGR ≈ 13.90%(交叉校验,trades/DD 应与 2010-06 一致)。

用法(bundle 加载~170s + 2 次回测~220s, 后台跑)
  nohup caffeinate -i -s python .../verify_report_baseline.py > logs/verify_report_baseline.log 2>&1 &
"""
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("verify_report_baseline")

from services.backtest import data_cache
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.portfolio.run_champions_solo import _run_solo
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_shared_pool import _pct

OUT_DIR = Path(__file__).resolve().parent
INITIAL_CAPITAL = 1_000_000  # BacktestEngine 默认(engine.py:61),_run_solo 未覆盖

# slow_growers 已发布冠军配置(逐字对齐 run_champions_solo.CHAMPIONS)
CHAMPION_OV = {
    "min_div_yield": 0.035,
    "mktcap_min_yi": 300.0,
    "top_n": 12,
    "max_per_sector": 2,
    "rebalance_months": [6],
}

# (窗口名, start, end, 报告原值备注 dict)
CASES = [
    ("report_2010_06", "2010-06-01", "2026-06-01",
     {"cagr": "14.28%", "total_return": "745.72%", "max_drawdown": "23.85%", "n_trades": 139,
      "role": "报告头条值·精确复现判据"}),
    ("report_2010_01", "2010-01-01", "2026-06-01",
     {"cagr": "13.90%", "max_drawdown": "23.85%", "n_trades": 139,
      "role": "报告注记口径·交叉校验(应与 2010-06 同 trades/DD)"}),
]


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)

    report = {
        "purpose": "slow_growers 冠军报告头条值(2010-06 起 14.28%)精确复现·INDUSTRY_NAME 修复后终局判据",
        "champion_overrides": CHAMPION_OV,
        "initial_capital": INITIAL_CAPITAL,
        "cases": {},
    }

    for name, start, end, expect in CASES:
        log.info("==== case %s (%s → %s) ====", name, start, end)
        sliced = data_cache.slice_bundle(bundle, None, start, end)
        t1 = time.time()
        m = _run_solo(sliced, LynchSlowGrowersStrategy, CHAMPION_OV)
        final_val = m.get("final_value")
        total_return = (final_val / INITIAL_CAPITAL - 1.0) if final_val else None
        m["total_return"] = total_return
        m["expect"] = expect
        report["cases"][name] = {"window": [start, end], **m}
        log.info(
            "[%s] %.1fs trades=%s CAGR=%s(报告%s) total=%s(报告%s) MaxDD=%s(报告%s) Sharpe=%.2f",
            name, time.time() - t1, m.get("n_trades"),
            _pct(m.get("cagr")), expect.get("cagr"),
            _pct(total_return), expect.get("total_return", "-"),
            _pct(m.get("max_drawdown")), expect.get("max_drawdown"),
            m.get("sharpe") or 0,
        )

    (OUT_DIR / "verify_report_baseline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    log.info("ALL DONE -> verify_report_baseline.json")


if __name__ == "__main__":
    main()
