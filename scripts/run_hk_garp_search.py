"""HK GARP 策略参数探索 —— 在全 H股 2010-2026 上找平均年化 ≥15%。

加载 HK bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

用法(后台):
  nohup python scripts/run_hk_garp_search.py --round 1 > logs/hk_garp_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hk_garp")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from strategies.utils import growth_hk, hk_industry
from strategies.examples.hk_garp_strategy import HkGarpStrategy

START = "2010-01-01"
END = "2026-06-01"

OUT_DIR = ROOT / "exported"
OUT_DIR.mkdir(exist_ok=True)


# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
M = list(range(1, 13))  # 月度调仓
# R6 真实可交易冠军基座(年度调仓 + 流动性10M + 5年CAGR窗口 = 8.58%)
BASE7 = {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5}
# R7 冠军基座(在 BASE7 上加 120 日趋势过滤 = 12.94%)
BASE8 = {**BASE7, "trend_ma_days": 120}
ROUNDS: dict[str, list] = {
    # Round 1: 基线 + 粗扫主因子(成长强度 / PEG / 持仓数 / 排序)
    "1": [
        ("R1_base", "基线 npCAGR15 PEG1.5 ROE10 Top20 peg", {}),
        ("R1_g20", "成长更强 npCAGR20", {"np_cagr_min": 0.20}),
        ("R1_g25", "成长更强 npCAGR25", {"np_cagr_min": 0.25}),
        ("R1_peg1", "PEG≤1.0", {"peg_max": 1.0}),
        ("R1_peg2", "PEG≤2.0", {"peg_max": 2.0}),
        ("R1_roe15", "ROE≥15", {"roe_min": 15.0}),
        ("R1_top10", "Top10 集中", {"top_n": 10}),
        ("R1_top30", "Top30 分散", {"top_n": 30}),
        ("R1_sortG", "按成长降序", {"sort_by": "growth"}),
        ("R1_sortC", "复合排序", {"sort_by": "composite"}),
    ],
    # Round 2: 组合两大赢家(ROE质量 + 分散),探索更宽篮子 + 价值陷阱地板 + 调仓频率
    "2": [
        ("R2_q15t30", "ROE15+Top30(组合双赢家)", {"roe_min": 15.0, "top_n": 30}),
        ("R2_q15t40", "ROE15+Top40", {"roe_min": 15.0, "top_n": 40}),
        ("R2_q15t50", "ROE15+Top50", {"roe_min": 15.0, "top_n": 50}),
        ("R2_t40", "Top40", {"top_n": 40}),
        ("R2_t50", "Top50", {"top_n": 50}),
        ("R2_q20t30", "ROE20+Top30(强质量)", {"roe_min": 20.0, "top_n": 30}),
        ("R2_q15t30_pegfl", "ROE15+Top30+PEG≥0.4(剔陷阱)",
         {"roe_min": 15.0, "top_n": 30, "peg_min": 0.4}),
        ("R2_q15t30_g", "ROE15+Top30+成长排序",
         {"roe_min": 15.0, "top_n": 30, "sort_by": "growth"}),
        ("R2_q15t30_pe25", "ROE15+Top30+PE≤25",
         {"roe_min": 15.0, "top_n": 30, "pe_max": 25.0}),
        ("R2_q15t30_Q", "ROE15+Top30+季度调仓",
         {"roe_min": 15.0, "top_n": 30, "rebalance_months": [3, 6, 9, 12]}),
    ],
    # Round 3: 以纯 Top30(R1 冠军)为基, 逐一探未测维度——调仓时点/流动性/CAGR窗口/ROE连续性/Top微调
    "3": [
        ("R3_t25", "Top25(20~30间)", {"top_n": 25}),
        ("R3_t35", "Top35", {"top_n": 35}),
        ("R3_t30_liq10", "Top30+日均成交≥1000万HKD",
         {"top_n": 30, "min_amount_hkd": 1e7}),
        ("R3_t30_liq50", "Top30+日均成交≥5000万HKD",
         {"top_n": 30, "min_amount_hkd": 5e7}),
        ("R3_t30_cagr2", "Top30+CAGR窗口2年", {"top_n": 30, "cagr_years": 2}),
        ("R3_t30_cagr5", "Top30+CAGR窗口5年", {"top_n": 30, "cagr_years": 5}),
        ("R3_t30_roeC3", "Top30+ROE连续3年达标",
         {"top_n": 30, "roe_consistency_years": 3}),
        # HK 报告披露日历对齐:年报~4月(+120d≈8月可见)、中报~8月(+90d≈11月可见)
        ("R3_t30_reb_sep_dec", "Top30+9/12月调仓(贴披露)",
         {"top_n": 30, "rebalance_months": [9, 12]}),
        ("R3_t30_monthly", "Top30+月度调仓", {"top_n": 30, "rebalance_months": list(range(1, 13))}),
        ("R3_t30_liq10_cagr2", "Top30+流动性10M+CAGR2年",
         {"top_n": 30, "min_amount_hkd": 1e7, "cagr_years": 2}),
    ],
    # Round 4: 决定性验证——月度调仓破15%是否是流动性幻象 + 稳健性变体
    # (amount 列恒0 已修复为 volume×close 成交额代理)
    "4": [
        ("R4_M", "月度Top30(复现16%)", {"top_n": 30, "rebalance_months": M}),
        ("R4_M_liq5", "月度+成交额≥500万HKD", {"top_n": 30, "rebalance_months": M, "min_amount_hkd": 5e6}),
        ("R4_M_liq10", "月度+成交额≥1000万HKD", {"top_n": 30, "rebalance_months": M, "min_amount_hkd": 1e7}),
        ("R4_M_liq30", "月度+成交额≥3000万HKD", {"top_n": 30, "rebalance_months": M, "min_amount_hkd": 3e7}),
        ("R4_M_cagr5", "月度+CAGR5年(更稳)", {"top_n": 30, "rebalance_months": M, "cagr_years": 5}),
        ("R4_M_roe15", "月度+ROE15", {"top_n": 30, "rebalance_months": M, "roe_min": 15.0}),
        ("R4_M_liq10_roe15", "月度+成交额10M+ROE15", {"top_n": 30, "rebalance_months": M, "min_amount_hkd": 1e7, "roe_min": 15.0}),
        ("R4_bimonthly", "双月调仓(降换手)", {"top_n": 30, "rebalance_months": [1, 3, 5, 7, 9, 11]}),
        ("R4_M_t20", "月度+Top20", {"top_n": 20, "rebalance_months": M}),
        ("R4_M_liq10_cagr5", "月度+成交额10M+CAGR5(主候选)",
         {"top_n": 30, "rebalance_months": M, "min_amount_hkd": 1e7, "cagr_years": 5}),
    ],
    # Round 5: 真实可交易上限——低换手(半年/季/年)+ 强制流动性, 看 GARP edge 能否在可交易标的上存活
    "5": [
        ("R5_S_liq5", "半年调仓+成交额≥500万", {"top_n": 30, "min_amount_hkd": 5e6}),
        ("R5_S_liq10", "半年调仓+成交额≥1000万", {"top_n": 30, "min_amount_hkd": 1e7}),
        ("R5_S_liq20", "半年调仓+成交额≥2000万", {"top_n": 30, "min_amount_hkd": 2e7}),
        ("R5_Q_liq10", "季度调仓+成交额≥1000万",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [3, 6, 9, 12]}),
        ("R5_A_liq10", "年度调仓+成交额≥1000万",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6]}),
        ("R5_S_liq10_t50", "半年+流动性10M+Top50(扩篮子)",
         {"top_n": 50, "min_amount_hkd": 1e7}),
        ("R5_S_liq10_roe15", "半年+流动性10M+ROE15",
         {"top_n": 30, "min_amount_hkd": 1e7, "roe_min": 15.0}),
        ("R5_S_liq10_cagr5", "半年+流动性10M+CAGR5",
         {"top_n": 30, "min_amount_hkd": 1e7, "cagr_years": 5}),
        ("R5_S_liq5_t50", "半年+流动性5M+Top50",
         {"top_n": 50, "min_amount_hkd": 5e6}),
        ("R5_bimonthly_liq10", "双月+流动性10M",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [1, 3, 5, 7, 9, 11]}),
    ],
    # Round 6: 真实可交易策略精修——固定"年度调仓+流动性"基座(R5 冠军 7.79%), 叠加质量/成长/篮子/时点
    "6": [
        ("R6_A_liq10_cagr5", "年度+流动性10M+CAGR5",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5}),
        ("R6_A_liq10_roe15", "年度+流动性10M+ROE15",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "roe_min": 15.0}),
        ("R6_A_liq10_cagr5_roe15", "年度+流动性10M+CAGR5+ROE15",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5, "roe_min": 15.0}),
        ("R6_A_liq5", "年度+流动性5M(更宽)",
         {"top_n": 30, "min_amount_hkd": 5e6, "rebalance_months": [6]}),
        ("R6_A_liq10_t20", "年度+流动性10M+Top20",
         {"top_n": 20, "min_amount_hkd": 1e7, "rebalance_months": [6]}),
        ("R6_A_liq10_t50", "年度+流动性10M+Top50",
         {"top_n": 50, "min_amount_hkd": 1e7, "rebalance_months": [6]}),
        ("R6_A_liq10_sep", "年度+流动性10M+9月调仓(贴中报)",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [9]}),
        ("R6_A_liq10_g20", "年度+流动性10M+npCAGR≥20",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "np_cagr_min": 0.20}),
        ("R6_A_liq10_cagr5_g", "年度+流动性10M+CAGR5+成长排序",
         {"top_n": 30, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5, "sort_by": "growth"}),
        ("R6_A_liq10_cagr5_t50", "年度+流动性10M+CAGR5+Top50",
         {"top_n": 50, "min_amount_hkd": 1e7, "rebalance_months": [6], "cagr_years": 5}),
    ],
    # Round 7: 方向①趋势/择时 + 方向②动量, 叠在 R6 冠军基座(年度+流动性10M+CAGR5=8.58%)上
    # 假设:流动池里低 PEG 名是"无动量的价值陷阱", 加趋势/动量过滤应能修复弱 edge
    "7": [
        ("R7_base", "基座:年度+流动性10M+CAGR5", BASE7),
        ("R7_trend200", "+趋势:close>200日线", {**BASE7, "trend_ma_days": 200}),
        ("R7_trend120", "+趋势:close>120日线", {**BASE7, "trend_ma_days": 120}),
        ("R7_trend60", "+趋势:close>60日线", {**BASE7, "trend_ma_days": 60}),
        ("R7_minmom0", "+动量门槛:近6月涨幅≥0",
         {**BASE7, "momentum_days": 120, "min_momentum": 0.0}),
        ("R7_sortmom6", "+按6月动量排序(追强)",
         {**BASE7, "momentum_days": 120, "sort_by": "momentum"}),
        ("R7_sortmom12", "+按12月动量排序",
         {**BASE7, "momentum_days": 250, "sort_by": "momentum"}),
        ("R7_garpmom6", "+GARP×动量复合排序(6月)",
         {**BASE7, "momentum_days": 120, "sort_by": "garp_mom"}),
        ("R7_reversal6", "+反转:按6月动量升序(抄弱)",
         {**BASE7, "momentum_days": 120, "sort_by": "reversal"}),
        ("R7_trend200_garpmom", "+趋势200+GARP×动量",
         {**BASE7, "trend_ma_days": 200, "momentum_days": 120, "sort_by": "garp_mom"}),
    ],
    # Round 8: 把趋势冠军(BASE8=年度+流动性10M+CAGR5+trend120=12.94%)推向 15%
    # 趋势过滤已挡掉下跌价值陷阱 → 重测调仓频率(年度约束可放松?)+ 集中度 + 动量叠加
    "8": [
        ("R8_base", "趋势基座(复现12.94%)", BASE8),
        ("R8_semiann", "+半年调仓(趋势已防接刀)", {**BASE8, "rebalance_months": [5, 11]}),
        ("R8_quarter", "+季度调仓", {**BASE8, "rebalance_months": [3, 6, 9, 12]}),
        ("R8_monthly", "+月度调仓", {**BASE8, "rebalance_months": M}),
        ("R8_t20", "+Top20 集中", {**BASE8, "top_n": 20}),
        ("R8_t15", "+Top15 更集中", {**BASE8, "top_n": 15}),
        ("R8_ma150", "+趋势改150日线", {**BASE8, "trend_ma_days": 150}),
        ("R8_ma90", "+趋势改90日线", {**BASE8, "trend_ma_days": 90}),
        ("R8_sortmom6", "+趋势+按6月动量排序",
         {**BASE8, "momentum_days": 120, "sort_by": "momentum"}),
        ("R8_quarter_t20_mom", "+季度+Top20+动量排序(组合)",
         {**BASE8, "rebalance_months": [3, 6, 9, 12], "top_n": 20,
          "momentum_days": 120, "sort_by": "momentum"}),
    ],
    # Round 9: 收口——集中度梯度稳健性检查(避免 Top15 是运气点)+ 叠加双赢家(ma90+集中)
    "9": [
        ("R9_t10", "Top10(集中梯度)", {**BASE8, "top_n": 10}),
        ("R9_t12", "Top12", {**BASE8, "top_n": 12}),
        ("R9_t15", "Top15(复现14.95%)", {**BASE8, "top_n": 15}),
        ("R9_t18", "Top18", {**BASE8, "top_n": 18}),
        ("R9_t25", "Top25", {**BASE8, "top_n": 25}),
        ("R9_t15_ma90", "Top15+趋势90(双赢家)", {**BASE8, "top_n": 15, "trend_ma_days": 90}),
        ("R9_t15_semiann", "Top15+半年调仓",
         {**BASE8, "top_n": 15, "rebalance_months": [5, 11]}),
        ("R9_t15_ma90_semiann", "Top15+趋势90+半年(全叠)",
         {**BASE8, "top_n": 15, "trend_ma_days": 90, "rebalance_months": [5, 11]}),
        ("R9_t12_ma90", "Top12+趋势90", {**BASE8, "top_n": 12, "trend_ma_days": 90}),
        ("R9_t15_minmom0", "Top15+动量门槛≥0",
         {**BASE8, "top_n": 15, "momentum_days": 120, "min_momentum": 0.0}),
    ],
    # Round 10: 稳健性——同一组冠军配置在不同子区间跑(配合 --start/--end),看是否依赖单一行情
    "10": [
        ("CH_t10", "冠军 Top10+趋势120", {**BASE8, "top_n": 10}),
        ("CH_t12_ma90", "冠军 Top12+趋势90", {**BASE8, "top_n": 12, "trend_ma_days": 90}),
        ("CH_t15", "稳健 Top15+趋势120", {**BASE8, "top_n": 15}),
        ("CH_t20", "保守 Top20+趋势120", {**BASE8, "top_n": 20}),
    ],
    # Round 11: 行业龙头集中 —— 在进取冠军(Top12+趋势90,年度调仓=20.54%)与稳健(Top15)上叠加
    #   require_industry(只买有 yfinance 行业分类的≈大盘龙头)/ max_per_sector(行业分散)
    #   注:R9 已证半年调仓伤害收益(20.54%→12.29%),冠军基座一律年度调仓([6],来自 BASE7)
    "11": [
        ("R11_agg_base", "进取冠军基线 Top12+趋势90(无行业)",
         {**BASE8, "top_n": 12, "trend_ma_days": 90}),
        ("R11_agg_indonly", "进取+仅龙头(require_industry)",
         {**BASE8, "top_n": 12, "trend_ma_days": 90, "require_industry": True}),
        ("R11_agg_sec2", "进取+每行业≤2",
         {**BASE8, "top_n": 12, "trend_ma_days": 90, "max_per_sector": 2}),
        ("R11_agg_sec3", "进取+每行业≤3",
         {**BASE8, "top_n": 12, "trend_ma_days": 90, "max_per_sector": 3}),
        ("R11_agg_ind_sec2", "进取+仅龙头+每行业≤2",
         {**BASE8, "top_n": 12, "trend_ma_days": 90,
          "require_industry": True, "max_per_sector": 2}),
        ("R11_rob_base", "稳健 Top15 基线(无行业)", {**BASE8, "top_n": 15}),
        ("R11_rob_indonly", "稳健+仅龙头",
         {**BASE8, "top_n": 15, "require_industry": True}),
        ("R11_rob_sec2", "稳健+每行业≤2", {**BASE8, "top_n": 15, "max_per_sector": 2}),
        ("R11_rob_sec3", "稳健+每行业≤3", {**BASE8, "top_n": 15, "max_per_sector": 3}),
        ("R11_rob_ind_sec3", "稳健+仅龙头+每行业≤3",
         {**BASE8, "top_n": 15, "require_industry": True, "max_per_sector": 3}),
    ],
    # Round 12: 行业冠军配置的样本外稳健性(配 --start/--end 分段)
    #   sec2/sec3 = 纯分散(无额外选择偏差,可信);ind_sec2 = 最优但放大幸存者偏差
    "12": [
        ("R12_agg_sec2", "进取 Top12+趋势90+每行业≤2(纯分散)",
         {**BASE8, "top_n": 12, "trend_ma_days": 90, "max_per_sector": 2}),
        ("R12_agg_ind_sec2", "进取+仅龙头+每行业≤2(最优,偏差大)",
         {**BASE8, "top_n": 12, "trend_ma_days": 90,
          "require_industry": True, "max_per_sector": 2}),
        ("R12_rob_sec3", "稳健 Top15+每行业≤3(纯分散)",
         {**BASE8, "top_n": 15, "max_per_sector": 3}),
    ],
}


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _run_one(sliced, tag, note, overrides):
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
    t0 = time.time()
    result = engine.run()
    elapsed = time.time() - t0
    m = result["metrics"]
    n_trades = len(result.get("raw_trades", []))
    summary = {
        "tag": tag,
        "note": note,
        "overrides": overrides,
        "elapsed_sec": round(elapsed, 1),
        "n_trades": n_trades,
        **m,
    }
    log.info(
        "[%s] %.1fs annual=%s total=%s mdd=%s sharpe=%.2f trades=%d | %s",
        tag,
        elapsed,
        _pct(m.get("annualized_return")),
        _pct(m.get("total_return")),
        _pct(m.get("max_drawdown")),
        m.get("sharpe_ratio", 0),
        n_trades,
        note,
    )
    return summary


def _write(summaries, round_tag):
    out_json = OUT_DIR / f"hk_garp_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# HK GARP 参数探索 Round {round_tag}",
        "",
        f"区间 {START} → {END} | 全 H股 | 完成 {len(ok)}/{len(summaries)}",
        "",
        "| 排名 | tag | 年化 | 总收益 | 最大回撤 | Sharpe | 笔数 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, s in enumerate(ok, 1):
        lines.append(
            f"| {i} | {s['tag']} | **{_pct(s['annualized_return'])}** | "
            f"{_pct(s['total_return'])} | {_pct(s['max_drawdown'])} | "
            f"{s.get('sharpe_ratio', 0):.2f} | {s['n_trades']} | {s['note']} |"
        )
    (OUT_DIR / f"hk_garp_r{round_tag}_overview.md").write_text("\n".join(lines))


def main():
    global START, END
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="1")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--label", default="", help="输出文件后缀(区分子区间跑)")
    args = ap.parse_args()
    configs = ROUNDS.get(args.round)
    if not configs:
        log.error("unknown round %s; available: %s", args.round, list(ROUNDS))
        return
    START, END = args.start, args.end
    start, end = args.start, args.end
    round_label = f"{args.round}{args.label}"

    growth_hk.reset_cache()
    hk_industry.reset_cache()
    log.info("加载 HK bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, start, end)
    log.info("sliced %d stocks iter[%d,%d] %s→%s", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx, start, end)

    summaries = []
    for tag, note, ov in configs:
        try:
            summaries.append(_run_one(sliced, tag, note, ov))
        except Exception as e:
            log.exception("[%s] FAILED: %s", tag, e)
            summaries.append({"tag": tag, "note": note, "error": str(e)})
        _write(summaries, round_label)

    log.info("DONE round %s (%s→%s) -> exported/hk_garp_r%s_overview.md",
             args.round, start, end, round_label)


if __name__ == "__main__":
    main()
