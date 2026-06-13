"""诊断:同配置 sec2 在同一进程内重复跑 N 次,看是否进程内确定。
配合外部不同 PYTHONHASHSEED 多次调用,判断是否存在哈希种子级非确定性。
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from services.backtest import data_cache  # noqa: E402
from services.backtest.engine import BacktestEngine  # noqa: E402
from strategies.utils import growth_hk, hk_industry  # noqa: E402
from strategies.deployed.hk_garp_strategy import HkGarpStrategy  # noqa: E402

START, END = "2010-01-01", "2026-06-01"
BASE7 = {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5}
BASE8 = {**BASE7, "trend_ma_days": 120}
CONFIG = {**BASE8, "top_n": 12, "trend_ma_days": 90, "max_per_sector": 2}

seed = os.environ.get("PYTHONHASHSEED", "<unset>")
print(f"### PYTHONHASHSEED={seed}")

growth_hk.reset_cache()
hk_industry.reset_cache()
bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
sliced = data_cache.slice_bundle(bundle, None, START, END)
print(f"universe={len(sliced.stock_data)}")


def run_once(i):
    strat = HkGarpStrategy(param_overrides=CONFIG)
    eng = BacktestEngine(
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
        enable_decision_log=False,
    )
    t0 = time.time()
    r = eng.run()
    m = r["metrics"]
    print(
        f"  run#{i}: annual={m.get('annualized_return',0):.4%} "
        f"total={m.get('total_return',0):.2%} trades={len(r['raw_trades'])} "
        f"({time.time()-t0:.0f}s)"
    )


for i in range(1, 4):
    run_once(i)
