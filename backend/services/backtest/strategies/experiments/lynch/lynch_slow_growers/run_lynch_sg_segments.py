#!/usr/bin/env python3
"""林奇·缓慢增长型 — 6月调仓最优配置 · 等长嵌套分段稳健性检验。

把全期 2010-06-01 → 2026-06-01(16 年整,以年度 6 月调仓日对齐)等分为
1/2/4/8/16 段,每段独立回测固定的「6月调仓最优画像」,观察年化在时间轴上
是否稳健,还是靠某几段堆出来。

边界全部落在 06-01(= 年度调仓日),与策略调仓周期对齐,避免短段「建仓前
空仓」扭曲;且 2/4/8/16 段边界严格嵌套(便于跨粒度对照)。

复用主矩阵脚本的 _run_one / _benchmark_annualized / 数据加载,故 bundle 只
加载一次,30+ 段都在同一 bundle 上切片跑。
"""
import importlib.util
import json
import logging
import statistics
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sg_seg")

# 动态加载主矩阵脚本,复用其函数与模块引用(__name__ != __main__,不触发其 main)
_spec = importlib.util.spec_from_file_location(
    "sgmatrix", str(Path(__file__).parent / "run_lynch_slow_growers_matrix.py"))
sgm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sgm)

# 6 月调仓最优画像(R6 全场最优:全期 13.90% / 回撤 23.85% / Sharpe 0.68)
BEST = {"min_div_yield": 0.035, "mktcap_min_yi": 300.0,
        "top_n": 12, "max_per_sector": 2, "rebalance_months": [6]}

ANCHOR_START_YEAR = 2010  # 06-01 首次调仓
ANCHOR_END_YEAR = 2026    # 06-01 终点 → 16 年整
TOTAL_YEARS = ANCHOR_END_YEAR - ANCHOR_START_YEAR  # 16
SEG_COUNTS = [1, 2, 4, 8, 16]


def _boundaries(n):
    """n 段等分,边界对齐 06-01。要求 16 % n == 0(嵌套整分)。"""
    assert TOTAL_YEARS % n == 0, f"{TOTAL_YEARS} 不能被 {n} 整除"
    step = TOTAL_YEARS // n
    return [f"{ANCHOR_START_YEAR + step * i:04d}-06-01" for i in range(n + 1)]


def _write(all_results):
    """增量写 JSON + Markdown 排行(每跑完一组分段就刷新)。"""
    (sgm.OUT_DIR / "lynch_sg_segments.json").write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2, default=str))
    lines = [
        "# 林奇·缓慢增长型 — 6月调仓最优配置 · 等长嵌套分段稳健性检验",
        "",
        "配置:股息≥3.5% + 市值≥300亿 + 行业≤2 + Top12 + yield降序 + "
        "**年度6月调仓** + 严守成长≤8%",
        "全期 2010-06-01 → 2026-06-01(16 年整,边界对齐 6 月调仓日,2/4/8/16 嵌套)",
        "",
    ]
    for n in SEG_COUNTS:
        segs = all_results.get(str(n))
        if not segs:
            continue
        anns = [s["annualized_return"] for s in segs
                if s.get("annualized_return") is not None]
        win = sum(1 for s in segs
                  if s.get("annualized_return") is not None
                  and s.get("bench_annual") is not None
                  and s["annualized_return"] > s["bench_annual"])
        neg = sum(1 for a in anns if a < 0)
        lines.append(f"## {n} 分段(每段 {TOTAL_YEARS // n} 年)")
        if anns:
            sd = sgm._pct(statistics.pstdev(anns)) if len(anns) > 1 else "-"
            lines.append(
                f"年化:均值 {sgm._pct(statistics.mean(anns))} | "
                f"最低 {sgm._pct(min(anns))} | 最高 {sgm._pct(max(anns))} | "
                f"标准差 {sd} | 负收益 {neg}/{len(segs)} 段 | "
                f"跑赢基准 {win}/{len(segs)} 段")
        lines.append("")
        lines.append("| 段 | 区间 | 年化 | 总收益 | 最大回撤 | Sharpe | "
                     "笔数 | 基准年化 | 超额 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for s in segs:
            ann = s.get("annualized_return")
            ba = s.get("bench_annual")
            excess = (ann - ba) if (ann is not None and ba is not None) else None
            lines.append(
                f"| {s['seg_idx']} | {s['seg_start'][:7]}→{s['seg_end'][:7]} | "
                f"**{sgm._pct(ann)}** | {sgm._pct(s.get('total_return'))} | "
                f"{sgm._pct(s.get('max_drawdown'))} | "
                f"{s.get('sharpe_ratio', 0):.2f} | {s.get('n_trades', 0)} | "
                f"{sgm._pct(ba)} | {sgm._pct(excess)} |")
        lines.append("")
    (sgm.OUT_DIR / "lynch_sg_segments_overview.md").write_text("\n".join(lines))


def main():
    log.info("加载 A bundle ...")
    sgm.growth_long.reset_annual_cache()
    sgm.st_filter.reset_st_cache()
    t0 = time.time()
    bundle = (sgm.data_cache.get_market("A")
              or sgm.data_cache._load_market_blocking("A"))
    log.info("bundle loaded %d stocks in %.1fs",
             len(bundle.stock_data), time.time() - t0)

    all_results = {}
    t_all = time.time()
    for n in SEG_COUNTS:
        bs = _boundaries(n)
        log.info(">>> %d 分段 (每段 %d 年): %s", n, TOTAL_YEARS // n, bs)
        seg_summaries = []
        for i in range(n):
            s, e = bs[i], bs[i + 1]
            sliced = sgm.data_cache.slice_bundle(bundle, None, s, e)
            tag = f"seg{n:02d}_{i + 1:02d}"
            summ = sgm._run_one(sliced, tag, f"{n}分段·第{i + 1}段 {s}→{e}", BEST)
            b_ann, b_tot = sgm._benchmark_annualized(s, e)
            summ.update({"seg_idx": i + 1, "seg_start": s, "seg_end": e,
                         "bench_annual": b_ann, "bench_total": b_tot})
            seg_summaries.append(summ)
        all_results[str(n)] = seg_summaries
        _write(all_results)  # 每组跑完即刷新
    log.info("ALL DONE %d 组分段 in %.0fs", len(SEG_COUNTS), time.time() - t_all)


if __name__ == "__main__":
    main()
