"""彼得·林奇「缓慢增长型」A 股策略 —— 发布版(最优画像)单次全期回测 + 报告数据导出。

用发布固化版 deployed/lynch_slow_growers_strategy.py 的默认参数(即最优画像),在
2010-01-01 → 2026-07-04 全 A 股跑一次完整回测,导出撰写研究报告所需的全部证据:
  - 全周期业绩指标(年化 / 累计 / 回撤 / Sharpe / 胜率 / 盈亏比 / 交易笔数 / 回合数)
  - 沪深300 基准对比(同区间年化 / 总收益)
  - 嵌套分段(1/2/4/8/16 段)每段收益与回撤(时间稳健性)
  - 全部买卖回合逐笔明细(含股票中文名称,便于人读)
  - 期初 / 期末资产、参数快照(发布默认值)

产物:lynch_sg_deployed_report.json(自闭环落本策略目录,作为可复现的研究时点证据)。

用法(后台跑,约数分钟):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_slow_growers/run_lynch_slow_growers_deployed_report.py \\
      > logs/lynch_sg_deployed_report.log 2>&1 &
"""

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

# 本脚本随策略处于 experiments/lynch/lynch_slow_growers/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_sg_deployed")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import growth_long, st_filter
from services.backtest.strategies.deployed.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.market_data import stock_index

START = "2010-01-01"
END = "2026-07-04"
CSI300_CODE = "CSI300"  # v_a_index 里沪深300 的 _symbol 标识

# 自闭环:回测产物(json)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_JSON = OUT_DIR / "lynch_sg_deployed_report.json"


def _annualized(total, years):
    """年化收益率:(1+total)^(1/years)-1。口径与引擎一致(years=自然日/365.25)。"""
    if years is None or years <= 0 or total is None or total <= -1:
        return None
    return (1 + total) ** (1 / years) - 1


def _seg_metrics(equity, i0, i1):
    """equity[i0..i1] 段内 total_return / annualized / max_drawdown。"""
    sub = equity[i0 : i1 + 1]
    if len(sub) < 2:
        return None
    v0 = sub[0]["total_value"]
    v1 = sub[-1]["total_value"]
    total = v1 / v0 - 1.0 if v0 > 0 else None
    d0 = date.fromisoformat(sub[0]["date"][:10])
    d1 = date.fromisoformat(sub[-1]["date"][:10])
    years = (d1 - d0).days / 365.25
    # 段内最大回撤(独立于全周期,从段起点重新计峰值)
    peak = sub[0]["total_value"]
    mdd = 0.0
    for e in sub:
        v = e["total_value"]
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return {
        "start": sub[0]["date"][:10],
        "end": sub[-1]["date"][:10],
        "years": round(years, 2),
        "total_return": round(total, 6) if total is not None else None,
        "annualized_return": round(_annualized(total, years) or 0.0, 6),
        "max_drawdown": round(mdd, 6),
        "value_start": round(v0, 2),
        "value_end": round(v1, 2),
    }


def _segment(equity, n_seg):
    """把 equity_curve 按点数(交易日)均分为 n_seg 段,返回每段业绩。"""
    n = len(equity)
    if n < 2:
        return []
    segs = []
    for k in range(n_seg):
        i0 = k * (n - 1) // n_seg
        i1 = (k + 1) * (n - 1) // n_seg
        m = _seg_metrics(equity, i0, i1)
        if m is not None:
            segs.append(m)
    return segs


def _benchmark(start, end):
    """沪深300 区间年化 / 总收益(基准对比)。视图缺失/数据不足返 (None, None)。"""
    try:
        from services.market_data.duckdb_store import get_store

        df = get_store().query_index("A", CSI300_CODE, start, end)
        if df is None or df.empty or "close" not in df.columns or len(df) < 2:
            return None, None
        closes = df["close"].dropna()
        if len(closes) < 2:
            return None, None
        first, last = float(closes.iloc[0]), float(closes.iloc[-1])
        total = last / first - 1.0
        d0 = date.fromisoformat(str(df["date"].iloc[0])[:10])
        d1 = date.fromisoformat(str(df["date"].iloc[-1])[:10])
        years = (d1 - d0).days / 365.25
        return _annualized(total, years), total
    except Exception as e:
        log.warning("benchmark CSI300 failed: %s", e)
        return None, None


def main():
    t_all = time.time()

    # PIT 缓存清零(与 matrix runner 一致,保证年报/ST 时点缓存干净)
    growth_long.reset_annual_cache()
    st_filter.reset_st_cache()

    # 加载代码→名称索引(独立脚本不经 main.py lifespan,须显式 init)
    try:
        stock_index.init_stock_index()
    except Exception as e:
        log.warning("init_stock_index failed(名称将留空): %s", e)

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info(
        "bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0
    )
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info(
        "sliced %d stocks iter[%d,%d] %s→%s",
        len(sliced.stock_data),
        sliced.iter_start_idx,
        sliced.iter_end_idx,
        START,
        END,
    )

    # 发布版:不传 param_overrides ⇒ 默认参数 = 最优画像
    strat = LynchSlowGrowersStrategy()
    engine = BacktestEngine(
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

    log.info("running backtest %s → %s ...", START, END)
    t1 = time.time()
    result = engine.run()
    log.info("backtest done in %.1fs", time.time() - t1)

    metrics = result["metrics"]
    equity = result["equity_curve"]
    round_trips = result["trades"]  # buy/sell 配对后的回合
    raw_trades = result["raw_trades"]  # 单边成交

    # 给每笔回合附股票中文名称(便于报告人读)
    for rt in round_trips:
        rt["name"] = stock_index.get_name(rt.get("symbol", "")) or ""

    bench_annual, bench_total = _benchmark(START, END)

    # 嵌套分段(1/2/4/8/16),对齐发布版 docstring 的时间稳健性口径
    segments = {str(n): _segment(equity, n) for n in (1, 2, 4, 8, 16)}

    initial = equity[0]["total_value"] if equity else 1_000_000.0
    final = equity[-1]["total_value"] if equity else initial

    # 参数快照:直接取发布版 params 的 default(自证最优画像)
    param_defaults = {k: v.get("default") for k, v in strat.params.items()}

    payload = {
        "strategy": "LynchSlowGrowersStrategy(deployed / 发布最优画像)",
        "generated_at": date.today().isoformat(),
        "period": {
            "requested_start": START,
            "requested_end": END,
            "equity_start": equity[0]["date"][:10] if equity else None,
            "equity_end": equity[-1]["date"][:10] if equity else None,
        },
        "initial_capital": round(initial, 2),
        "final_value": round(final, 2),
        "params_deployed_defaults": param_defaults,
        "metrics": metrics,
        "benchmark_csi300": {
            "annualized_return": bench_annual,
            "total_return": bench_total,
        },
        "n_raw_trades": len(raw_trades),
        "n_round_trips": len(round_trips),
        "segments": segments,
        "round_trips": round_trips,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    log.info("wrote %s", OUT_JSON)

    seg1 = segments["1"][0] if segments["1"] else {}
    log.info(
        "SUMMARY annual=%.2f%% total=%.2f%% mdd=%.2f%% sharpe=%.2f "
        "win=%.1f%% pf=%.2f raw_trades=%d round_trips=%d | CSI300 annual=%s",
        metrics.get("annualized_return", 0) * 100,
        metrics.get("total_return", 0) * 100,
        metrics.get("max_drawdown", 0) * 100,
        metrics.get("sharpe_ratio", 0),
        metrics.get("win_rate", 0) * 100,
        metrics.get("profit_factor", 0),
        len(raw_trades),
        len(round_trips),
        f"{bench_annual * 100:.2f}%" if bench_annual is not None else "-",
    )
    log.info("ALL DONE in %.0fs", time.time() - t_all)


if __name__ == "__main__":
    main()
