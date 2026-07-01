"""林奇·困境反转型 —— 连续持仓分段稳健性验证(1/2/4/8/16 段)。

对冠军配置 debt60 跑一次全样本(2010-01-01→2026-06-01)连续回测,取逐日净值曲线,
按 equity_curve 实际时间跨度等分成 1/2/4/8/16 段(≈16/8/4/2/1 年/段),
每段用"段末净值 ÷ 段初净值"折算年化。

🚨 连续持仓口径(与既有两种验证刻意不同):
  - §2.4 缓慢增长型  = 各段独立从空仓重建(每段当作一次独立回测, 段初建仓/段末清仓)
  - champ p1/p2/p3   = 三段各自独立回测
  - 本脚本(连续持仓) = 一次连续回测, 只在同一条 equity_curve 上切点 → 段初持仓 = 上一段
    结束时的满仓状态(继承, 不清仓 / 不重新建仓)。故各段(末净值/初净值)连乘 == 全样本
    总收益(可做自洽校验)。度量的是"若一直持有该策略, 每 8/4/2/1 年区间的真实体验"。

用法(后台跑, 单配置全样本约 3-6 分钟):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_turnarounds/run_lynch_tr_segments.py \
      > logs/lynch_tr_segments.log 2>&1 &
"""

import bisect
import json
import logging
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# 本脚本随策略自闭环在 experiments/lynch/lynch_turnarounds/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_tr_seg")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_turnarounds.lynch_turnarounds_strategy import (
    LynchTurnaroundsStrategy,
)
from services.market_data.duckdb_store import get_store

START = "2010-01-01"
END = "2026-06-01"
CSI300_CODE = "CSI300"

# debt60 冠军配置(= R5_debt60 / CH_debt60, 全样本 15.88%):
#   季度调仓 + Top10 集中 + 负债率≤60%(低杠杆存活), 其余走策略默认
#   (排金融 / PB≤2 / 扭亏 np_turn / 市值≥50亿)。
CHAMP_OVERRIDES = {"rebalance_months": [3, 6, 9, 12], "top_n": 10, "max_debt_ratio": 0.60}
SEGMENT_COUNTS = [1, 2, 4, 8, 16]

# 自闭环:产物直接落本策略目录
OUT_DIR = Path(__file__).resolve().parent


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _parse(d: str) -> datetime:
    return datetime.strptime(str(d)[:10], "%Y-%m-%d")


def _nearest_idx(dates: list[datetime], target: datetime) -> int:
    """升序 datetime 列表中找与 target 最接近的下标(二分)。"""
    i = bisect.bisect_left(dates, target)
    if i <= 0:
        return 0
    if i >= len(dates):
        return len(dates) - 1
    # 落在 dates[i-1] 与 dates[i] 之间,取更近者
    return i if (dates[i] - target) < (target - dates[i - 1]) else i - 1


def _max_drawdown(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    peak = values[0]
    mdd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd = dd
    return mdd


def _annualize(v_start: float, v_end: float, years: float):
    """区间年化,口径与 analyzer.compute_metrics 一致:(末/初)^(1/年)-1。"""
    if years <= 0 or v_start <= 0:
        return None
    return (v_end / v_start) ** (1 / years) - 1


def _index_series(start: str, end: str):
    """CSI300 全区间日线 → (升序 datetime 列表, close 列表),供分段基准对比。"""
    try:
        df = get_store().query_index("A", CSI300_CODE, start, end)
        if df is None or df.empty or "close" not in df.columns:
            return [], []
        df = df.dropna(subset=["close"])
        dates = [_parse(d) for d in df["date"].tolist()]
        closes = [float(c) for c in df["close"].tolist()]
        return dates, closes
    except Exception as e:
        log.warning("CSI300 series failed: %s", e)
        return [], []


def _run_full_backtest() -> dict:
    """全样本 debt60 连续回测,返回引擎完整 result(含逐日 equity_curve)。"""
    growth_long.reset_annual_cache()
    balance_long.reset_balance_cache()
    st_filter.reset_st_cache()
    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info("sliced %d stocks iter[%d,%d] %s→%s", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx, START, END)

    strat = LynchTurnaroundsStrategy(param_overrides=CHAMP_OVERRIDES)
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
    t0 = time.time()
    result = engine.run()
    m = result["metrics"]
    log.info("backtest done in %.1fs | annual=%s total=%s mdd=%s trades=%d",
             time.time() - t0, _pct(m.get("annualized_return")),
             _pct(m.get("total_return")), _pct(m.get("max_drawdown")),
             len(result.get("raw_trades", [])))
    return result


def _segment(eq_dates, eq_values, idx_dates, idx_closes, n: int) -> list[dict]:
    """把连续 equity 曲线按时间等分成 n 段,返回每段指标。

    段边界为 n+1 个等间隔日期(首尾锚定 equity 起止),段 k 的终点下标 == 段 k+1 的
    起点下标 → 严格连续持仓,无重复建仓。
    """
    t0, tend = eq_dates[0], eq_dates[-1]
    span = (tend - t0).days
    boundaries = [t0 + timedelta(days=span * k / n) for k in range(n + 1)]
    b_idx = [_nearest_idx(eq_dates, b) for b in boundaries]
    b_idx[0], b_idx[-1] = 0, len(eq_dates) - 1  # 首尾锚定,确保覆盖全程

    segs = []
    for k in range(n):
        si, ej = b_idx[k], b_idx[k + 1]
        v0, v1 = eq_values[si], eq_values[ej]
        d0, d1 = eq_dates[si], eq_dates[ej]
        years = (d1 - d0).days / 365.25
        seg_annual = _annualize(v0, v1, years)
        seg_total = (v1 / v0 - 1) if v0 > 0 else None
        seg_mdd = _max_drawdown(eq_values[si:ej + 1])
        # 同期 CSI300 年化(用相同起止日期各自定位最近交易日)
        bench_annual = None
        if idx_dates:
            bi, bj = _nearest_idx(idx_dates, d0), _nearest_idx(idx_dates, d1)
            if bj > bi:
                bench_annual = _annualize(idx_closes[bi], idx_closes[bj], years)
        excess = (seg_annual - bench_annual) if (
            seg_annual is not None and bench_annual is not None) else None
        segs.append({
            "k": k + 1,
            "start": d0.strftime("%Y-%m-%d"),
            "end": d1.strftime("%Y-%m-%d"),
            "years": round(years, 2),
            "annual": seg_annual,
            "total": seg_total,
            "mdd": seg_mdd,
            "bench_annual": bench_annual,
            "excess": excess,
        })
    return segs


def _summarize(segs: list[dict]) -> dict:
    annuals = [s["annual"] for s in segs if s["annual"] is not None]
    pos = sum(1 for a in annuals if a > 0)
    beat = sum(1 for s in segs if s["excess"] is not None and s["excess"] > 0)
    return {
        "min": min(annuals) if annuals else None,
        "median": statistics.median(annuals) if annuals else None,
        "max": max(annuals) if annuals else None,
        "pos": pos,
        "beat": beat,
        "n": len(segs),
    }


def _write_report(result: dict, all_segs: list[tuple[int, list[dict]]]):
    eq = result["equity_curve"]
    m = result["metrics"]
    lines = [
        "# 林奇·困境反转型 · 连续持仓分段稳健性(debt60 冠军)",
        "",
        "配置: 季度调仓 + Top10 + ≥50亿 + PB≤2 + 扭亏(np_turn) + **资产负债率≤60%** "
        "(= R5_debt60 / CH_debt60)",
        f"区间: {eq[0]['date']} → {eq[-1]['date']} | 全样本年化 "
        f"**{_pct(m.get('annualized_return'))}** / 总收益 {_pct(m.get('total_return'))} "
        f"/ 最大回撤 {_pct(m.get('max_drawdown'))} / Sharpe {m.get('sharpe_ratio', 0):.2f}",
        "",
        "🚨 **连续持仓口径**: 一次全样本连续回测, 只在同一条净值曲线上切点; 段初持仓 = "
        "上一段结束时的满仓状态(继承, 不清仓 / 不重新建仓)。各段(末/初)连乘 == 全样本总收益。",
        "与 §2.4(各段独立从空仓重建)、champ p1/p2/p3(三段独立回测)口径**不同**。",
        "",
        "## 跨粒度汇总",
        "",
        "| 段数 | 每段≈年限 | 年化 min | 年化 中位数 | 年化 max | 正收益段 | 跑赢沪深300段 |",
        "|---|---|---|---|---|---|---|",
    ]
    for n, segs in all_segs:
        s = _summarize(segs)
        yr = segs[0]["years"] if segs else 0
        lines.append(
            f"| {n} | {yr:.1f}年 | {_pct(s['min'])} | {_pct(s['median'])} | "
            f"{_pct(s['max'])} | {s['pos']}/{s['n']} | {s['beat']}/{s['n']} |"
        )

    for n, segs in all_segs:
        if n == 1:
            continue
        yr = segs[0]["years"] if segs else 0
        lines += [
            "",
            f"## {n} 段(每段≈{yr:.1f}年)",
            "",
            "| 段# | 起止 | 年限 | 策略年化 | 策略总收益 | 段内回撤 | 沪深300年化 | 超额(pp) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s in segs:
            lines.append(
                f"| {s['k']} | {s['start']}~{s['end']} | {s['years']:.2f} | "
                f"**{_pct(s['annual'])}** | {_pct(s['total'])} | {_pct(s['mdd'])} | "
                f"{_pct(s['bench_annual'])} | {_pct(s['excess'])} |"
            )

    (OUT_DIR / "lynch_tr_segments_overview.md").write_text("\n".join(lines))
    (OUT_DIR / "lynch_tr_segments.json").write_text(json.dumps({
        "config": CHAMP_OVERRIDES,
        "metrics": m,
        "equity_first": {"date": eq[0]["date"], "total_value": eq[0]["total_value"]},
        "equity_last": {"date": eq[-1]["date"], "total_value": eq[-1]["total_value"]},
        "segments": {str(n): segs for n, segs in all_segs},
    }, ensure_ascii=False, indent=2, default=str))


def main():
    result = _run_full_backtest()
    eq = result["equity_curve"]
    if not eq or len(eq) < 2:
        log.error("equity_curve 为空或过短,无法分段")
        return
    eq_dates = [_parse(e["date"]) for e in eq]
    eq_values = [float(e["total_value"]) for e in eq]
    idx_dates, idx_closes = _index_series(START, END)

    # 自洽校验 1: 切段全样本年化 ≈ metrics 年化
    full_years = (eq_dates[-1] - eq_dates[0]).days / 365.25
    full_annual = _annualize(eq_values[0], eq_values[-1], full_years)
    log.info("自洽校验: 切段全样本年化=%s vs metrics年化=%s",
             _pct(full_annual), _pct(result["metrics"].get("annualized_return")))

    all_segs = []
    for n in SEGMENT_COUNTS:
        segs = _segment(eq_dates, eq_values, idx_dates, idx_closes, n)
        all_segs.append((n, segs))
        # 自洽校验 2: 各段(1+total)连乘 == 全样本(1+total)
        prod = 1.0
        for s in segs:
            if s["total"] is not None:
                prod *= (1 + s["total"])
        log.info("n=%2d: 各段连乘总收益=%s vs 全样本=%s | 年化 min/med/max=%s/%s/%s",
                 n, _pct(prod - 1), _pct(eq_values[-1] / eq_values[0] - 1),
                 _pct(_summarize(segs)["min"]), _pct(_summarize(segs)["median"]),
                 _pct(_summarize(segs)["max"]))

    _write_report(result, all_segs)
    log.info("ALL DONE -> %s", OUT_DIR / "lynch_tr_segments_overview.md")


if __name__ == "__main__":
    main()
