"""单跑 sec2 一次,打印 hashseed + 年化 + 笔数。外部用不同 PYTHONHASHSEED 调用。"""
import os
import sys
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

growth_hk.reset_cache()
hk_industry.reset_cache()
bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
sliced = data_cache.slice_bundle(bundle, None, START, END)

strat = HkGarpStrategy(param_overrides=CONFIG)
eng = BacktestEngine(
    strategy=strat, stock_data=sliced.stock_data,
    valuation_data=sliced.valuation_data, dividend_data=sliced.dividend_data,
    financial_data=sliced.financial_data, balance_data=sliced.balance_data,
    cashflow_data=sliced.cashflow_data, income_data=sliced.income_data,
    weekly_data=sliced.weekly_data, monthly_data=sliced.monthly_data,
    iter_start=sliced.iter_start_idx, iter_end=sliced.iter_end_idx,
    enable_decision_log=False,
)
r = eng.run()
m = r["metrics"]
# 取 sliced 键序前 5 个,看是否跨进程变化
keys5 = list(sliced.stock_data.keys())[:5]
print(
    f"RESULT seed={os.environ.get('PYTHONHASHSEED','<unset>')} "
    f"annual={m.get('annualized_return',0):.4%} trades={len(r['raw_trades'])} "
    f"keys5={keys5}",
    flush=True,
)
