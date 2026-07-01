#!/usr/bin/env python3
"""诊断:林奇·缓慢增长型 6月调仓最优画像,为什么 2015-06→2016-06 段 0 交易?

复用主矩阵脚本(sgmatrix)的数据加载 / 策略 / 引擎,对两个 1 年窗口各跑一次
**开启决策日志**的回测,然后读 flow.jsonl 的漏斗计数,定位 0 交易的成因:
  - 若 screen.done passed=0  → 漏斗筛空(看 valuation/growth/dividend 哪级归零)
  - 若 screen.done passed>0 但 trades=0 → regime 仓位=0(沪深300 避险)

对照组 2014-06→2015-06(真实成交 3 笔 / 92.79%)用于验证日志读取正确。
"""
import importlib.util
import json
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("diag_sg")

_spec = importlib.util.spec_from_file_location(
    "sgmatrix", str(Path(__file__).parent / "run_lynch_slow_growers_matrix.py"))
sgm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sgm)

BEST = {"min_div_yield": 0.035, "mktcap_min_yi": 300.0,
        "top_n": 12, "max_per_sector": 2, "rebalance_months": [6]}

WINDOWS = [
    ("2014-06-01", "2015-06-01", "ctrl_2014_traded"),  # 对照:应成交
    ("2015-06-01", "2016-06-01", "zero_2015"),          # 目标:0 交易
]

DIAG_DIR = sgm.OUT_DIR / "diag_sg_2015"


def _run_with_log(bundle, start, end, tag):
    sliced = sgm.data_cache.slice_bundle(bundle, None, start, end)
    log_dir = DIAG_DIR / tag
    strat = sgm.LynchSlowGrowersStrategy(param_overrides=BEST)
    engine = sgm.BacktestEngine(
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
        log_dir=log_dir,
        enable_decision_log=True,
    )
    t0 = time.time()
    result = engine.run()
    n_trades = len(result.get("raw_trades", []))
    log.info("[%s] %s→%s  trades=%d  elapsed=%.1fs  log_dir=%s",
             tag, start, end, n_trades, time.time() - t0, log_dir)

    # 读 flow.jsonl,只看 6 月(调仓月)的漏斗事件
    flow_path = log_dir / "flow.jsonl"
    if not flow_path.exists():
        log.warning("[%s] flow.jsonl 不存在", tag)
        return
    june_events = []
    for line in flow_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        ts = str(rec.get("ts", ""))
        if ts[5:7] == "06":  # 6 月
            june_events.append(rec)
    log.info("[%s] === 6月漏斗事件(共 %d 条)===", tag, len(june_events))
    for rec in june_events:
        log.info("[%s]   %s | %s | counts=%s",
                 tag, rec.get("ts"), rec.get("stage"), rec.get("counts"))


def main():
    t0 = time.time()
    bundle = (sgm.data_cache.get_market("A")
              or sgm.data_cache._load_market_blocking("A"))
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    for start, end, tag in WINDOWS:
        _run_with_log(bundle, start, end, tag)
    log.info("DIAG DONE in %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()
