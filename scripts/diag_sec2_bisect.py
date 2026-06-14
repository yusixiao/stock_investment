"""二分:同一进程内,同一份 sliced bundle 上跑两次回测。
若两次结果不同 → 非确定性在 ENGINE.run();若相同 → 在数据 LOAD 阶段。"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from services.backtest import data_cache  # noqa: E402
from services.backtest.engine import BacktestEngine  # noqa: E402
from services.backtest.strategies.utils import growth_hk, hk_industry  # noqa: E402
from services.backtest.strategies.deployed.hk_garp_strategy import HkGarpStrategy  # noqa: E402

START, END = "2010-01-01", "2026-06-01"
CONFIG = {
    "top_n": 12, "min_amount_hkd": 1e7, "rebalance_months": [6],
    "cagr_years": 5, "trend_ma_days": 90, "max_per_sector": 2,
}

growth_hk.reset_cache()
hk_industry.reset_cache()
bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
sliced = data_cache.slice_bundle(bundle, None, START, END)


def run_once():
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
    return r["metrics"].get("annualized_return", 0), len(r["raw_trades"])


for i in range(3):
    a, t = run_once()
    print(f"RUN {i}: annual={a:.4%} trades={t}", flush=True)
