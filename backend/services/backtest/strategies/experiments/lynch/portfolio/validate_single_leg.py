#!/usr/bin/env python3
"""Exp-3 引擎保真验证 · 单腿复现 (full 全期窗口)。

背景
----
Exp-3(``run_portfolio_shared_pool.py``)是"一份现金同时跑三腿"的单账户真回测, Exp-2 则是
各腿独立净值按权重混合的乐观估计。二者数字必有差额, 但差额必须能被**现实摩擦**(成本 / 整手 /
现金约束 / 重叠净额 / within-leg 再平衡)完全解释; 若 meta 引擎自身有 look-ahead / 账务 /
现金复用 bug, 差额会失真。故须验证 meta 引擎是否**忠实还原单条腿**。

方法
----
用 ``LynchMetaComboStrategy`` 只装一条腿(weight=1.0), 真回测, 与 Exp-2 缓存的该腿
standalone 逐日收益(``legs_daily_returns_full.parquet``, 同样是含成本的真回测)对照。
- ``on_change``: 仅腿真正改持仓的月份交易, **最贴近 standalone**(唯一残差=调仓月 len 不变时
  保留仓不被重置等权 → 任其漂移)。若 CAGR ≈ standalone(±~0.5%), 证明引擎无系统性放大。
- ``monthly``: 每月把该腿持仓重置等权(比 standalone 的自身调仓周期更频繁), 用于量化
  「within-leg 再平衡频率」这一维度的影响。

判读
----
- 若 on_change 单腿 ≈ standalone → 引擎忠实, 组合上翘是真实的**个股层组合交互**(caveat: 高波动)。
- 若 meta 单腿显著高于 standalone → meta 有 bug(look-ahead / 账务 / 现金复用), 须继续排查。

用法(长任务, 后台跑):
  nohup python backend/services/backtest/strategies/experiments/lynch/portfolio/validate_single_leg.py \
      > logs/lynch_validate_single_leg.log 2>&1 &
"""
import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lynch_validate")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.portfolio.lynch_meta_combo_strategy import (
    LynchMetaComboStrategy,
)
from services.backtest.strategies.experiments.lynch.portfolio.run_portfolio_shared_pool import (
    _metrics,
    LEG_CONFIGS,
    OUT_DIR,
)

WNAME = "full"
START, END = "2010-01-01", "2026-06-01"
MODES = ["monthly", "on_change"]
LEG_BY_NAME = {name: (cls, ov) for name, cls, ov in LEG_CONFIGS}


def _run_single(sliced, leg_name, mode):
    """meta 只装 leg_name 一条腿(weight=1.0)真回测 → 指标 dict。"""
    cls, ov = LEG_BY_NAME[leg_name]
    legs = [(leg_name, cls(param_overrides=ov))]
    meta = LynchMetaComboStrategy(legs=legs, weights={leg_name: 1.0}, rebalance_mode=mode)
    engine = BacktestEngine(
        strategy=meta,
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
    )
    res = engine.run()
    ec = res.get("equity_curve") or []
    if not ec:
        return {"cagr": None, "n_trades": 0}
    vals = pd.Series(
        [float(p["total_value"]) for p in ec],
        index=pd.to_datetime([p["date"] for p in ec]),
    ).sort_index()
    daily = vals.pct_change().dropna()
    m = _metrics(daily)
    m["n_trades"] = len(res.get("raw_trades", []) or [])
    m["final_value"] = round(float(vals.iloc[-1]), 2)
    return m


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, START, END)

    R = pd.read_parquet(OUT_DIR / f"legs_daily_returns_{WNAME}.parquet")

    log.info("================ 单腿复现验证 (%s: %s → %s) ================", WNAME, START, END)
    for leg in ["slow_growers", "turnarounds", "asset_plays"]:
        base = _metrics(R[leg].dropna())
        log.info(
            "[%s] standalone(Exp-2 parquet, 含成本): CAGR=%.2f%% Sharpe=%.2f MaxDD=%.2f%% days=%d",
            leg, base["cagr"] * 100, base["sharpe"], base["max_drawdown"] * 100, base["n_days"],
        )
        for mode in MODES:
            t = time.time()
            m = _run_single(sliced, leg, mode)
            dc = (m["cagr"] - base["cagr"]) * 100 if m.get("cagr") is not None else None
            log.info(
                "[%s] meta{1.0}/%-9s: %.1fs CAGR=%.2f%% Sharpe=%.2f MaxDD=%.2f%% trades=%d final=%.0f  Δcagr=%+.2f%%",
                leg, mode, time.time() - t, m["cagr"] * 100, m["sharpe"],
                m["max_drawdown"] * 100, m["n_trades"], m["final_value"], dc,
            )
    log.info("================ 验证完成 ================")


if __name__ == "__main__":
    main()
