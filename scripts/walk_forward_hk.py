"""Walk-forward 稳健性验证(滚动多粒度 · 不重训,只验证)。

设计(用户 2026 口径):
  不做"分段重新训练"。参数 = R1-R20 在全期 2010-2026 选出的【固定冠军】,
  之后绝不再训。把时间线切成不同粒度(2 段 / 4 段 / 8 段 / 16 段,最细到 1 年,
  不再往下拆),只【验证】这个固定参数的策略在每一段里的表现是否在 base 上下
  一个合理带内波动。目标 = 找出【牛市熊市都有稳健收益】的策略。

  判优 ≠ 总收益最高,而是【抗跌优先 + 跨牛熊稳定】。用户例子:
    策略A 牛+50/熊-40/总+25  vs  策略B 牛+35/熊-5/总+20  → 要 B 胜出。
  打分公式:  Score = 全期CAGR − λ × 最差单年亏损(取正幅度)
    λ=1 时: A = 0.25 − 0.40 = -0.15 ;  B = 0.20 − 0.05 = +0.15  → B 胜。✓

为什么不切独立窗口(沿用 R20 决策):
  GARP 6 月调仓,独立年度窗口每段从空仓起步、6 月才建仓 → 每段仅约 7 个月持仓,
  失真且不可比;早期窗口因 5 年 CAGR lookback 不足选不出股。
  正解 = 每个候选【只跑一次连续回测 2010-2026】,再把 equity_curve 按 K 切片,
  从净值曲线算每段收益。段与段连续可比、无空仓缺口,一次运行导出全部 4 种粒度。

牛熊标签 = 同区间恒指(HSI)涨跌(客观):>+5% 牛 / <-5% 熊 / 其余震荡。

用法(后台,等 R1-R20 冠军出来后再执行):
  python scripts/bg_launch.py logs/hk_walk_forward.log \
      python scripts/walk_forward_hk.py --lam 1.0
  # 可选: --ks 2,4,8,16  --start 2010-01-01 --end 2026-06-01  --band 0.15
"""

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hk_walk_forward")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.market_data.duckdb_store import get_store
from services.backtest.strategies.utils import growth_hk, hk_industry
from services.backtest.strategies.deployed.hk_garp_strategy import HkGarpStrategy

START = "2010-01-01"
END = "2026-06-01"
OUT_DIR = ROOT / "report" / "exported"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- 复用 run_hk_garp_search 的基座定义(保持口径一致) ----
BASE7 = {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5}
BASE8 = {**BASE7, "trend_ma_days": 120}
BASE_R14 = {**BASE8, "top_n": 12, "trend_ma_days": 90,
            "require_industry": True, "max_per_sector": 2}
BASE_G25 = {**BASE_R14, "np_cagr_min": 0.25}

# ---- 候选集(option b)----
# 不重训:这里是【固定参数】的几个候选,各跑一次连续回测后用抗跌分横向比较。
# 2026-06-14 干净基线 + R21 便宜度下沿探测后,全期年化排名(同 2010-2026 段):
#   PE15      28.81% sharpe0.99 mdd40.02%  ← 🏆 全期新冠军(BASE_R14+pe_max15),H1#1/H2#2 已验证
#   PE20      23.55% sharpe0.86 mdd41.33%  ← 旧冠军(BASE_R14+pe_max20)
#   G20_PE25  22.68% sharpe0.82 mdd43.42%
#   PE25      21.55% sharpe0.80 mdd43.43%
#   PE10      21.96% sharpe0.78 mdd39.38%  ← 倒 U 跌回,Score 负(价值陷阱,已排除)
#   BASE_R14  19.23%                       ← 基座(无便宜度过滤)
# 便宜度梯度 = 倒 U(峰在 PE≤15);抗跌 Score(CAGR−λ·最差年):pe15 +12.97 > pe20 +5.13 > pe10 −5.03。
# ⚠️ walk-forward 用于检验候选在 K=2/4/8/16 时间切片下是否稳健(抗跌优先),而非再次按全期挑冠军。
# 每项: (tag, note, param_overrides)
CANDIDATES: list[tuple[str, str, dict]] = [
    ("PE15", "全期新冠军 PE≤15(BASE_R14+pe15)", {**BASE_R14, "pe_max": 15.0}),
    ("PE10", "PE≤10(下沿,疑价值陷阱)", {**BASE_R14, "pe_max": 10.0}),
    ("PE20", "旧冠军 PE≤20(BASE_R14+pe20)", {**BASE_R14, "pe_max": 20.0}),
    ("G20_PE25", "成长≥20 + PE≤25", {**BASE_R14, "np_cagr_min": 0.20, "pe_max": 25.0}),
    ("PEG10_PE25", "PEG≤1.0 + PE≤25(双便宜度)", {**BASE_R14, "peg_max": 1.0, "pe_max": 25.0}),
    ("PE25", "PE≤25(防泡沫)", {**BASE_R14, "pe_max": 25.0}),
    ("BASE_G25", "最优成长内核(基线参照)", BASE_G25),
    ("BASE_R14", "冠军基座(无便宜度过滤)", BASE_R14),
]


def _pct(x):
    return "-" if x is None else f"{x * 100:+.2f}%"


def _year_end_values(equity_curve):
    """每个日历年最后一个净值点 -> {year: (date, value)}(升序覆盖即得年末点)。"""
    by_year = {}
    for pt in equity_curve:
        by_year[int(pt["date"][:4])] = (pt["date"], float(pt["value"]))
    return by_year


def _span_mdd(equity_curve, year_set):
    """给定年份集合内的峰谷最大回撤(正数)。"""
    vals = [float(pt["value"]) for pt in equity_curve
            if int(pt["date"][:4]) in year_set]
    if not vals:
        return None
    peak = vals[0]
    worst = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > worst:
            worst = dd
    return worst


def _hsi_year_end():
    """恒指年末收盘 {year: close}。"""
    df = get_store().query_index("HK", "HSI", START, END)
    if df is None or df.empty or "close" not in df.columns:
        log.warning("HSI 数据不可用,跳过牛熊标签")
        return {}
    by_year = {}
    for d_str, c in zip(df["date"], df["close"]):
        try:
            by_year[int(str(d_str)[:4])] = float(c)
        except (TypeError, ValueError):
            continue
    return by_year


def _array_split(seq, k):
    """把有序序列近似等分成 k 个连续块(numpy.array_split 的纯 Python 版)。"""
    n = len(seq)
    k = min(k, n)
    base, extra = divmod(n, k)
    chunks = []
    i = 0
    for j in range(k):
        size = base + (1 if j < extra else 0)
        chunks.append(seq[i:i + size])
        i += size
    return chunks


def _annualize(period_ret, n_years):
    """把区间累计收益换算成年化(n_years 为该段覆盖的年数)。"""
    if period_ret is None or n_years <= 0:
        return None
    return (1.0 + period_ret) ** (1.0 / n_years) - 1.0


def _regime(hsi_ret):
    if hsi_ret is None:
        return "?"
    if hsi_ret > 0.05:
        return "🐂牛"
    if hsi_ret < -0.05:
        return "🐻熊"
    return "震荡"


def _run_candidate(sliced, overrides):
    """跑一次连续回测,返回 (metrics, equity_curve, init_cap)。"""
    strat = HkGarpStrategy(param_overrides=overrides)
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
    result = engine.run()
    return result["metrics"], result["equity_curve"], float(engine._initial_capital)


def _decompose(equity_curve, init_cap, hsi_year_end, ks):
    """把连续净值按多种粒度 K 切片。

    返回 {K: [seg_dict, ...]},seg_dict 含 span/years/seg_return/annualized/
    hsi_return/regime/intra_mdd。
    """
    year_end = _year_end_values(equity_curve)
    years = sorted(year_end)  # 含早期 + 可能的 2026 部分年
    out = {}
    for k in ks:
        chunks = _array_split(years, k)
        segs = []
        prev_value = init_cap
        for chunk in chunks:
            if not chunk:
                continue
            first_y, last_y = chunk[0], chunk[-1]
            end_val = year_end[last_y][1]
            seg_ret = end_val / prev_value - 1 if prev_value > 0 else None
            # 牛熊:用 HSI 在 (first_y 前一年末 -> last_y 年末) 的涨跌
            hsi_start = hsi_year_end.get(first_y - 1)
            hsi_end = hsi_year_end.get(last_y)
            hsi_ret = (hsi_end / hsi_start - 1
                       if hsi_start and hsi_end and hsi_start > 0 else None)
            n_years = len(chunk)
            segs.append({
                "span": f"{first_y}-{last_y}" if first_y != last_y else f"{first_y}",
                "years": n_years,
                "seg_return": seg_ret,
                "annualized": _annualize(seg_ret, n_years),
                "hsi_return": hsi_ret,
                "regime": _regime(hsi_ret),
                "intra_mdd": _span_mdd(equity_curve, set(chunk)),
            })
            prev_value = end_val
        out[k] = segs
    return out


def _robustness(metrics, decomp, lam, band):
    """抗跌优先的稳健性打分。

    - cagr           : 全期年化(reward)
    - worst_year_loss: 最细粒度(年)里最差单年亏损幅度(正数,downside)
    - score          : cagr - lam * worst_year_loss  (A/B 例子的数学化)
    - 其余:各 K 的离散度/最差段、牛熊均值、落在 base±band 内的段数。
    """
    cagr = metrics.get("annualized_return")
    # 最细粒度 = 最大的 K(年级)
    finest_k = max(decomp) if decomp else None
    yearly = decomp.get(finest_k, []) if finest_k else []
    yearly_rets = [s["seg_return"] for s in yearly if s["seg_return"] is not None]
    worst_year = min(yearly_rets) if yearly_rets else None
    worst_year_loss = max(0.0, -worst_year) if worst_year is not None else None

    score = None
    if cagr is not None and worst_year_loss is not None:
        score = cagr - lam * worst_year_loss

    # 牛熊分组(用最细粒度,标签最干净)
    bull = [s["seg_return"] for s in yearly
            if s["regime"] == "🐂牛" and s["seg_return"] is not None]
    bear = [s["seg_return"] for s in yearly
            if s["regime"] == "🐻熊" and s["seg_return"] is not None]

    def _avg(xs):
        return sum(xs) / len(xs) if xs else None

    # 各 K 的离散度 / 最差段 / band 命中(用年化口径与 base CAGR 公平对比)
    per_k = {}
    for k, segs in decomp.items():
        anns = [s["annualized"] for s in segs if s["annualized"] is not None]
        rets = [s["seg_return"] for s in segs if s["seg_return"] is not None]
        mean = sum(anns) / len(anns) if anns else None
        std = None
        if anns and mean is not None:
            std = (sum((a - mean) ** 2 for a in anns) / len(anns)) ** 0.5
        in_band = None
        if cagr is not None and anns:
            in_band = sum(1 for a in anns if abs(a - cagr) <= band)
        per_k[k] = {
            "n": len(segs),
            "mean_annualized": mean,
            "std_annualized": std,
            "worst_seg_return": min(rets) if rets else None,
            "in_band": in_band,
        }

    return {
        "cagr": cagr,
        "worst_year_return": worst_year,
        "worst_year_loss": worst_year_loss,
        "score": score,
        "bull_avg": _avg(bull),
        "bear_avg": _avg(bear),
        "n_bull": len(bull),
        "n_bear": len(bear),
        "per_k": per_k,
    }


def _render(results, lam, band, ks):
    """results: [{tag, note, overrides, metrics, decomp, robust}]"""
    ranked = [r for r in results if r["robust"]["score"] is not None]
    ranked.sort(key=lambda r: r["robust"]["score"], reverse=True)

    lines = [
        "# HK Walk-forward 稳健性验证(滚动多粒度 · 不重训)",
        "",
        f"区间 {START} → {END} | 全 H股 | 连续回测后按 K={ks} 切片",
        f"打分: Score = CAGR − λ×最差单年亏损 (λ={lam}) | band=±{band * 100:.0f}%",
        "",
        "> 不重训,只验证固定参数在不同时间粒度下是否在 base 上下稳定波动。",
        "> 抗跌优先:最差单年亏损越小越好(用户 A/B 口径,B 胜 A)。",
        "> 牛熊标签 = 同区间恒指涨跌 >+5%牛 / <-5%熊 / 其余震荡。",
        "",
        "## 候选排名(按 Score 抗跌优先)",
        "",
        "| 排名 | 候选 | Score | 全期CAGR | 最差单年 | 🐂牛均值 | 🐻熊均值 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranked, 1):
        rb = r["robust"]
        lines.append(
            f"| {i} | {r['tag']} | **{_pct(rb['score'])}** | "
            f"{_pct(rb['cagr'])} | {_pct(rb['worst_year_return'])} | "
            f"{_pct(rb['bull_avg'])}({rb['n_bull']}) | "
            f"{_pct(rb['bear_avg'])}({rb['n_bear']}) | {r['note']} |"
        )

    # 每候选的多粒度明细
    for r in results:
        rb = r["robust"]
        lines += [
            "",
            f"## {r['tag']} — {r['note']}",
            "",
            f"全期: CAGR {_pct(rb['cagr'])} | 最差单年 {_pct(rb['worst_year_return'])} "
            f"| Score {_pct(rb['score'])}",
            "",
            "粒度稳定性(年化口径 vs base CAGR):",
            "",
            "| K(段数) | 段数 | 年化均值 | 年化波动(std) | 最差段收益 | 落在band内 |",
            "|---|---|---|---|---|---|",
        ]
        for k in sorted(r["decomp"]):
            pk = rb["per_k"][k]
            band_cell = "-" if pk["in_band"] is None else f"{pk['in_band']}/{pk['n']}"
            std_cell = "-" if pk["std_annualized"] is None else f"{pk['std_annualized'] * 100:.2f}%"
            lines.append(
                f"| {k} | {pk['n']} | {_pct(pk['mean_annualized'])} | {std_cell} | "
                f"{_pct(pk['worst_seg_return'])} | {band_cell} |"
            )
        # 最细粒度逐段表
        finest_k = max(r["decomp"])
        lines += [
            "",
            f"最细粒度(K={finest_k})逐段:",
            "",
            "| 区间 | 市场 | 段收益 | 年化 | 恒指 | 段内最大回撤 |",
            "|---|---|---|---|---|---|",
        ]
        for s in r["decomp"][finest_k]:
            mdd = "-" if s["intra_mdd"] is None else f"{s['intra_mdd'] * 100:.2f}%"
            lines.append(
                f"| {s['span']} | {s['regime']} | **{_pct(s['seg_return'])}** | "
                f"{_pct(s['annualized'])} | {_pct(s['hsi_return'])} | {mdd} |"
            )

    (OUT_DIR / "hk_walk_forward.md").write_text("\n".join(lines))


def main():
    global START, END
    ap = argparse.ArgumentParser()
    ap.add_argument("--lam", type=float, default=1.0,
                    help="抗跌惩罚系数: Score = CAGR − λ×最差单年亏损")
    ap.add_argument("--ks", default="2,4,8,16",
                    help="切片粒度(段数),逗号分隔;最细到 1 年(16 段)")
    ap.add_argument("--band", type=float, default=0.15,
                    help="稳定带半宽(年化口径),统计落在 base±band 内的段数")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--only", default="",
                    help="只跑指定 tag(逗号分隔),空=全部 CANDIDATES")
    args = ap.parse_args()

    START, END = args.start, args.end
    ks = sorted({int(x) for x in args.ks.split(",") if x.strip()})
    only = {t.strip() for t in args.only.split(",") if t.strip()}
    candidates = [c for c in CANDIDATES if not only or c[0] in only]
    if not candidates:
        log.error("--only %s 未匹配任何 tag; 可选: %s",
                  args.only, [c[0] for c in CANDIDATES])
        return

    growth_hk.reset_cache()
    hk_industry.reset_cache()
    log.info("加载 HK bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, START, END)
    log.info("sliced %d stocks iter[%d,%d] %s→%s", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx, START, END)

    hsi_ye = _hsi_year_end()

    results = []
    for tag, note, ov in candidates:
        try:
            t1 = time.time()
            metrics, eq, init_cap = _run_candidate(sliced, ov)
            decomp = _decompose(eq, init_cap, hsi_ye, ks)
            robust = _robustness(metrics, decomp, args.lam, args.band)
            log.info("[%s] %.1fs CAGR=%s worstYr=%s score=%s | %s",
                     tag, time.time() - t1, _pct(robust["cagr"]),
                     _pct(robust["worst_year_return"]), _pct(robust["score"]), note)
            results.append({"tag": tag, "note": note, "overrides": ov,
                            "metrics": metrics, "decomp": decomp, "robust": robust})
        except Exception as e:
            log.exception("[%s] FAILED: %s", tag, e)
            results.append({"tag": tag, "note": note, "overrides": ov,
                            "metrics": {}, "decomp": {},
                            "robust": {"score": None}, "error": str(e)})
        # 增量落盘(每个候选完成即写,长任务可中途看)
        _render(results, args.lam, args.band, ks)
        (OUT_DIR / "hk_walk_forward.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str))

    log.info("DONE -> exported/hk_walk_forward.md (+ .json)")


if __name__ == "__main__":
    main()
