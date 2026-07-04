#!/usr/bin/env python3
"""林奇六型「元组合」相关性研究 (Exp-1) —— 组合化研究的地基与闸门。

目的: 把六型策略(各自诚实/可部署配置)在同一窗口、同一 A 股 bundle 上各跑一遍
完整回测, 抽取逐日净值曲线, 换算「月度收益率」序列, 计算跨型相关性矩阵 + 各型
独立风险收益指标。用于判断多型组合是否具备分散价值(低相关 → 有降波动/压回撤空间)。

🚨 方法学(与用户三口径决策一致):
- 相关性口径 = 月度收益率(低换手策略, 日度波动≈市场 beta 噪声, 会系统性高估相关)。
- 每型配置 = 诚实/可部署版本(周期型用朴素基线 6.43%, 而非过拟合冠军 11.11%;
  隐蔽资产型用冠军 K4 但诚实值看 2016+; 其余用各自研究冠军), 见 TYPES 常量的来源注释。
- 窗口: 全期(2010-01 → 2026-06)单一口径。since2016 窗口 + 牛/熊子区间已弃
  (2026-07-04): 对组合选腿无增量信息, full 全期即主口径。
- 各型 CAGR/MaxDD/Sharpe 用引擎指标(日度口径, 与各型研究报告一致);
  相关矩阵用月度收益(口径不同, 勿混用两套数字)。
- 🚨 每型均为独立标准回测(各自满仓现金起步、各自复利), 这是「元组合」曲线级研究;
  真正的共享资金池 / 统一再平衡属 Exp-3, 本脚本不做。

用法(长任务, 必须后台跑):
  nohup python backend/services/backtest/strategies/experiments/lynch/portfolio/run_portfolio_corr.py \
      > logs/lynch_portfolio_corr.log 2>&1 &
  # 前台只查进度: tail -f logs/lynch_portfolio_corr.log
"""
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

# 本脚本位于 experiments/lynch/portfolio/, 上溯 7 层到项目根(与同级 lynch_* runner 一致)
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("lynch_portfolio")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_stalwarts.lynch_stalwarts_strategy import (
    LynchStalwartsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_turnarounds.lynch_turnarounds_strategy import (
    LynchTurnaroundsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_cyclicals.lynch_cyclicals_strategy import (
    LynchCyclicalsStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_asset_plays.asset_plays_strategy import (
    LynchAssetPlaysStrategy,
)
from services.backtest.strategies.experiments.lynch.lynch_fast_growers.lynch_fast_growers_strategy import (
    LynchFastGrowersStrategy,
)

CSI300_CODE = "CSI300"  # v_a_index 里沪深300 的 _symbol 标识
OUT_DIR = Path(__file__).resolve().parent

# 六型 (name, StrategyClass, 诚实/可部署 param_overrides)。
# 每型 overrides 均直接取自该型自己 runner 里的冠军/基线配置(来源注释见右), 保证与研究报告口径一致。
TYPES = [
    # slow_growers: run_lynch_sg_segments.py::BEST (R6 6月调仓最优, 全期 13.90%)
    ("slow_growers", LynchSlowGrowersStrategy,
     {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12,
      "max_per_sector": 2, "rebalance_months": [6]}),
    # stalwarts: run_lynch_stalwarts_matrix.py::CHAMP D基 cap250 sec2 (≈11.24%)
    ("stalwarts", LynchStalwartsStrategy,
     {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
      "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
    # turnarounds: run_lynch_turnarounds_matrix.py::CH_debt60 (季度+Top10+负债率≤60%, 全期 15.88%)
    ("turnarounds", LynchTurnaroundsStrategy,
     {"rebalance_months": [3, 6, 9, 12], "top_n": 10, "max_debt_ratio": 0.60}),
    # cyclicals: run_lynch_cyclicals_matrix.py::CH_base 朴素基线(诚实 6.43%, 非过拟合冠军 11.11%)
    ("cyclicals", LynchCyclicalsStrategy,
     {"trailing_stop_pct": 0.25}),
    # asset_plays: run_lynch_asset_plays_matrix.py::CHAMP_trend150 K4 (全期 14.73% / 2016+ 诚实 8.38%)
    ("asset_plays", LynchAssetPlaysStrategy,
     {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
      "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150}),
    # fast_growers: 收敛后默认值即冠军(15~100亿/g25/月度/Top25, +4.48%), 空 overrides 即冠军
    ("fast_growers", LynchFastGrowersStrategy, {}),
]

WINDOWS = {
    "full": ("2010-01-01", "2026-06-01"),  # 全期单一口径(since2016 窗口已弃, 2026-07-04)
}


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _run(strat_cls, overrides, sliced):
    """在已切片 bundle 上跑一型完整回测, 返回引擎 result。"""
    strat = strat_cls(param_overrides=overrides)
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
    )
    return engine.run()


def _equity_monthly_returns(equity_curve):
    """逐日净值曲线 → 月末净值 → 月度收益率(PeriodIndex)。"""
    if not equity_curve:
        return None
    dates = pd.to_datetime([p["date"] for p in equity_curve])
    vals = pd.Series([float(p["total_value"]) for p in equity_curve], index=dates).sort_index()
    monthly = vals.groupby(vals.index.to_period("M")).last()
    return monthly.pct_change().dropna()


def _csi300_monthly_returns(start, end):
    """沪深300 月度收益率, 作为相关矩阵里的市场基准列。"""
    try:
        from services.market_data.duckdb_store import get_store

        df = get_store().query_index("A", CSI300_CODE, start, end)
        if df is None or df.empty or "close" not in df.columns:
            return None
        idx = pd.to_datetime(df["date"])
        s = pd.Series(df["close"].astype(float).values, index=idx).sort_index()
        m = s.groupby(s.index.to_period("M")).last()
        return m.pct_change().dropna()
    except Exception as e:
        log.warning("CSI300 monthly returns failed: %s", e)
        return None


def _corr_block(ret_df):
    """相关矩阵 + 平均非对角相关 + 相关对(升序)。NaN(常数列/样本不足)安全跳过。"""
    corr = ret_df.corr()
    cols = list(corr.columns)
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr.iloc[i, j]
            if v == v:  # 非 NaN
                pairs.append((cols[i], cols[j], round(float(v), 3)))
    off = [p[2] for p in pairs]

    def cell(a, b):
        v = corr.loc[a, b]
        return round(float(v), 3) if v == v else None

    return {
        "matrix": {c: {c2: cell(c, c2) for c2 in cols} for c in cols},
        "avg_offdiag": round(sum(off) / len(off), 3) if off else None,
        "pairs_sorted": sorted(pairs, key=lambda x: x[2]),
    }


def _write_overview(report):
    """增量写 markdown 排行/矩阵(每跑完一个窗口刷新一次)。"""
    fmt = lambda v: "-" if v is None else f"{v:.2f}"
    lines = [
        "# 林奇六型元组合 · 相关性研究 (Exp-1)",
        "",
        "> 相关性口径 = **月度收益率**;各型 CAGR/MaxDD/Sharpe = 引擎**日度口径**(与研究报告一致), 两套数字勿混用。",
        "> 每型为独立标准回测(各自满仓现金起步、各自复利);共享资金池 / 统一再平衡属 Exp-3。",
        "> 周期型用**朴素基线**(诚实 6.43%), 非过拟合冠军;隐蔽资产型冠军全期虚高, 看 2016+ 诚实值。",
        "",
    ]
    for wname, block in report.items():
        lines += [f"## 窗口 `{wname}`", ""]
        lines += [
            "| 型 | 年化 | 总收益 | 最大回撤 | Sharpe | 笔数 |",
            "|---|---|---|---|---|---|",
        ]
        for name, m in block["metrics"].items():
            if "error" in m:
                lines.append(f"| {name} | ERROR | | | | {m['error']} |")
            else:
                lines.append(
                    f"| {name} | {_pct(m['annualized_return'])} | {_pct(m['total_return'])} | "
                    f"{_pct(m['max_drawdown'])} | {(m['sharpe_ratio'] or 0):.2f} | {m['n_trades']} |"
                )
        lines.append("")

        corr = block.get("corr")
        if corr:
            cols = list(corr["matrix"].keys())
            lines += [
                f"月度相关矩阵 (n={block['n_months']} 月, **平均非对角相关 {corr['avg_offdiag']}**):",
                "",
                "| | " + " | ".join(cols) + " |",
                "|" + "---|" * (len(cols) + 1),
            ]
            for c in cols:
                row = " | ".join(fmt(corr["matrix"][c][c2]) for c2 in cols)
                lines.append(f"| **{c}** | {row} |")
            lines += ["", "最低相关对(Top5, 越低越具分散价值):"]
            for a, b, v in corr["pairs_sorted"][:5]:
                lines.append(f"- {a} × {b}: **{v}**")
            lines.append("")

    (OUT_DIR / "portfolio_corr_overview.md").write_text("\n".join(lines))


def main():
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()

    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)

    report = {}
    for wname, (start, end) in WINDOWS.items():
        log.info("==== window %s (%s → %s) ====", wname, start, end)
        sliced = data_cache.slice_bundle(bundle, None, start, end)
        log.info("sliced %d stocks iter[%d,%d]", len(sliced.stock_data),
                 sliced.iter_start_idx, sliced.iter_end_idx)

        metrics, monthly = {}, {}
        for name, cls, ov in TYPES:
            t1 = time.time()
            try:
                res = _run(cls, ov, sliced)
                m = res["metrics"]
                metrics[name] = {
                    "annualized_return": m.get("annualized_return"),
                    "total_return": m.get("total_return"),
                    "max_drawdown": m.get("max_drawdown"),
                    "sharpe_ratio": m.get("sharpe_ratio"),
                    "n_trades": len(res.get("raw_trades", [])),
                }
                mr = _equity_monthly_returns(res.get("equity_curve"))
                if mr is not None and not mr.empty:
                    monthly[name] = mr
                log.info(
                    "[%s/%s] %.1fs annual=%s mdd=%s sharpe=%.2f trades=%d",
                    wname, name, time.time() - t1,
                    _pct(metrics[name]["annualized_return"]),
                    _pct(metrics[name]["max_drawdown"]),
                    metrics[name]["sharpe_ratio"] or 0,
                    metrics[name]["n_trades"],
                )
            except Exception as e:
                log.exception("[%s/%s] FAILED: %s", wname, name, e)
                metrics[name] = {"error": str(e)}

        bench = _csi300_monthly_returns(start, end)
        if bench is not None and not bench.empty:
            monthly["CSI300"] = bench

        ret_df = pd.DataFrame(monthly).dropna(how="any")
        block = {
            "window": [start, end],
            "metrics": metrics,
            "n_months": int(len(ret_df)),
            "corr": _corr_block(ret_df) if not ret_df.empty else None,
        }

        report[wname] = block
        _write_overview(report)  # 增量刷新

    (OUT_DIR / "portfolio_corr.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    log.info("ALL DONE -> portfolio_corr.json + portfolio_corr_overview.md")


if __name__ == "__main__":
    main()
