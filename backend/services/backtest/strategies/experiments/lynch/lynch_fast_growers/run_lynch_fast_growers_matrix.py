"""林奇·快速增长型(Fast Growers)A 股策略参数探索 —— 找平均年化 ≥15%。

加载 A 股 bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜(含沪深300基准)。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

用法:
  # 先 smoke 验证端到端(短区间, 前台快跑):
  python backend/services/backtest/strategies/experiments/lynch/lynch_fast_growers/run_lynch_fast_growers_matrix.py --round smoke --start 2018-01-01 --end 2020-01-01
  # 全期跑 Round 1(后台):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_fast_growers/run_lynch_fast_growers_matrix.py --round 1 > logs/lynch_fg_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本随策略迁入 experiments/lynch/lynch_fast_growers/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_fg")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import growth_long
from services.backtest.strategies.utils import st_filter
from services.backtest.strategies.experiments.lynch.lynch_fast_growers.lynch_fast_growers_strategy import (
    LynchFastGrowersStrategy,
)

START = "2010-01-01"
END = "2026-06-01"

# 自闭环:回测产物(json/overview.md)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

M = list(range(1, 13))  # 月度调仓

# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
# 策略默认: cagr∈[25%,50%], 营收CAGR≥15%, mktcap 20~300亿, ROE≥15, peg≤1, top15, peg排序, 年度5月调仓
ROUNDS: dict[str, list] = {
    # smoke: 单配置, 仅验证端到端可跑通(配短区间前台跑)
    "smoke": [
        ("FG_smoke", "默认配置 smoke 验证", {}),
    ],
    # Round 1: 粗扫林奇快速增长各主轴(调仓频率/成长带/市值带/集中度/估值/趋势/排序/质量)
    "1": [
        ("R1_base", "默认基线(年度5月调仓 cagr25-50 mktcap20-300 peg1 roe15 top15)", {}),
        ("R1_monthly", "月度调仓(用户口径)", {"rebalance_months": M}),
        ("R1_quarter", "季度调仓", {"rebalance_months": [3, 6, 9, 12]}),
        ("R1_g20", "成长下限放宽至20%(更多样本)", {"np_cagr_min": 0.20}),
        ("R1_nocapmax", "取消成长上限(纳入>50%高增)", {"np_cagr_max": 0.0}),
        ("R1_peg15", "PEG≤1.5(放宽估值纪律)", {"peg_max": 1.5}),
        ("R1_smallcap", "纯小盘 20~150亿", {"mktcap_max_yi": 150.0}),
        ("R1_midcap", "中盘 100~500亿", {"mktcap_min_yi": 100.0, "mktcap_max_yi": 500.0}),
        ("R1_top10", "Top10 集中", {"top_n": 10}),
        ("R1_top25", "Top25 分散", {"top_n": 25}),
        ("R1_trend200", "+趋势 close>200日线", {"trend_ma_days": 200}),
        ("R1_sortG", "按成长降序排序", {"sort_by": "growth"}),
        ("R1_roe20", "ROE≥20 强质量", {"roe_min": 20.0}),
    ],
    # Round 2: 以 R1 最佳「小盘20~150亿」为基座, 叠加两大有效杠杆(小盘+月度),
    # 并引入 regime 择时(沪深300跌破200日线降仓)正面压 66% 回撤 → 撬动复利逼近15%。
    # 学习: 市值越小越好(midcap 灾难)/ 成长上限必须留 / 集中度伤害 / 年度趋势过滤无力(无法持有期内离场)。
    "2": [
        ("R2_sc", "小盘20~150亿 基座(复现 R1 最佳)",
         {"mktcap_max_yi": 150.0}),
        ("R2_sc_monthly", "小盘 + 月度调仓(两强杠杆合并)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M}),
        ("R2_sc_smaller", "更小 10~80亿(推市值轴)",
         {"mktcap_min_yi": 10.0, "mktcap_max_yi": 80.0}),
        ("R2_sc_micro_monthly", "10~80亿 + 月度",
         {"mktcap_min_yi": 10.0, "mktcap_max_yi": 80.0, "rebalance_months": M}),
        ("R2_sc_regime0", "小盘 + regime 熊市空仓(200日线)",
         {"mktcap_max_yi": 150.0, "risk_off_exposure": 0.0, "regime_ma_days": 200}),
        ("R2_sc_regime30", "小盘 + regime 熊市3成仓",
         {"mktcap_max_yi": 150.0, "risk_off_exposure": 0.3, "regime_ma_days": 200}),
        ("R2_sc_monthly_regime30", "小盘 + 月度 + regime 3成(核心押注)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "risk_off_exposure": 0.3, "regime_ma_days": 200}),
        ("R2_sc_monthly_regime0", "小盘 + 月度 + regime 空仓",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "risk_off_exposure": 0.0, "regime_ma_days": 200}),
        ("R2_sc_monthly_trend", "小盘 + 月度 + 趋势200(持有期内可离场)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "trend_ma_days": 200}),
        ("R2_sc_capmax40", "小盘 + 成长上限收紧至40%",
         {"mktcap_max_yi": 150.0, "np_cagr_max": 0.40}),
        ("R2_sc_monthly_top25", "小盘 + 月度 + Top25 分散",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25}),
        ("R2_sc_quarter_regime30", "小盘 + 季度 + regime 3成(降换手)",
         {"mktcap_max_yi": 150.0, "rebalance_months": [3, 6, 9, 12], "risk_off_exposure": 0.3, "regime_ma_days": 200}),
    ],
    # Round 3: 锁定 R2 最佳架构「小盘150 + 月度 + Top25 分散」(+3.60%, 超基准),
    # 精扫剩余轴: 分散度 / 市值带微调 / 排序 / 估值纪律(PE·PEG下限避陷阱) / 成长带平移·营收质量。
    # 学习: regime/趋势入场全证伪(勿再试); 成长上限须留50%; 月度+分散是收益主引擎。
    # 注: sort_by 仅支持 peg/growth/composite(无 roe)。
    "3": [
        ("R3_base", "R2 最佳架构 复现(小盘150+月度+Top25)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25}),
        ("R3_top30", "Top30 更分散",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 30}),
        ("R3_top40", "Top40 更分散",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 40}),
        ("R3_size120", "市值上限收紧至120亿",
         {"mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
        ("R3_size200", "市值上限放宽至200亿",
         {"mktcap_max_yi": 200.0, "rebalance_months": M, "top_n": 25}),
        ("R3_size15_120", "市值带下移 15~120亿",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
        ("R3_sortG", "按成长降序排序(月度)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25, "sort_by": "growth"}),
        ("R3_sortComposite", "复合排序(低PEG+高成长 rank和)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25, "sort_by": "composite"}),
        ("R3_pe30", "PE上限收紧至30(估值纪律)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25, "pe_max": 30.0}),
        ("R3_pegmin03", "PEG下限0.3(避开过度便宜的伪低估陷阱)",
         {"mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25, "peg_min": 0.3}),
        ("R3_g30cap60", "成长带上移 30~60%",
         {"np_cagr_min": 0.30, "np_cagr_max": 0.60, "mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25}),
        ("R3_revcagr25", "营收CAGR≥25%(成长质量加严)",
         {"rev_cagr_min": 0.25, "mktcap_max_yi": 150.0, "rebalance_months": M, "top_n": 25}),
    ],
    # Round 4: 锁定 R3 最佳「15~120亿 + 月度 + Top25」(+4.43%, 总收益破100%),
    # 组合最优旋钮(15-120 × Top30)并在最优点附近精修市值带 + 轻度放宽样本(g22/roe12)+ 收紧PEG。
    # 学习: 市值上限是命门(120>150>>200); 下沿15>20; Top30是分散甜区; PEG排序且无下限; 成长带25-50%勿动。
    "4": [
        ("R4_base", "R3 最佳 复现(15~120亿+月度+Top25)",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
        ("R4_top30", "15~120 + Top30(两最优旋钮合并)",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 30}),
        ("R4_top35", "15~120 + Top35",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 35}),
        ("R4_size10_120", "下沿推至10亿 10~120",
         {"mktcap_min_yi": 10.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
        ("R4_size15_100", "上限收紧至100亿 15~100",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
        ("R4_size15_140", "上限放宽至140亿 15~140",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 140.0, "rebalance_months": M, "top_n": 25}),
        ("R4_size12_110", "居中 12~110亿",
         {"mktcap_min_yi": 12.0, "mktcap_max_yi": 110.0, "rebalance_months": M, "top_n": 25}),
        ("R4_top30_10_120", "10~120 + Top30",
         {"mktcap_min_yi": 10.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 30}),
        ("R4_top30_15_100", "15~100 + Top30",
         {"mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 30}),
        ("R4_g22", "成长下限放宽至22%(扩样本)",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
        ("R4_roe12", "ROE放宽至12%(扩样本)",
         {"roe_min": 12.0, "mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
        ("R4_peg085", "PEG上限收紧至0.85(更严低估)",
         {"peg_max": 0.85, "mktcap_min_yi": 15.0, "mktcap_max_yi": 120.0, "rebalance_months": M, "top_n": 25}),
    ],
    # Round 5(收敛定稿): 合并 R4 两独立赢家 g22(+4.75%) × 15~100亿(+4.48%,回撤47.5%),
    # 精扫成长下限(20/22/25)+ 市值上限(80/90/100/110)+ 下沿(12/15/18)+ 分散度, 收敛定稿配置。
    # 学习: 上限越紧越好(峰值80~100间)/ 下沿15最佳 / g22扩样本加分 / ROE15与PEG≤1守住 / regime·趋势勿用。
    "5": [
        ("R5_combo", "合并赢家 g22 + 15~100 + Top25(核心定稿候选)",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
        ("R5_combo_top30", "g22 + 15~100 + Top30",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 30}),
        ("R5_g20", "成长下限20% + 15~100",
         {"np_cagr_min": 0.20, "mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
        ("R5_g25", "成长下限25%(对照) + 15~100",
         {"np_cagr_min": 0.25, "mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
        ("R5_cap90", "g22 + 15~90(上限再紧)",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 90.0, "rebalance_months": M, "top_n": 25}),
        ("R5_cap80", "g22 + 15~80(逼近微盘峰)",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 80.0, "rebalance_months": M, "top_n": 25}),
        ("R5_cap110", "g22 + 15~110",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 110.0, "rebalance_months": M, "top_n": 25}),
        ("R5_floor12", "g22 + 12~100(下沿再放)",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 12.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
        ("R5_floor18", "g22 + 18~100(下沿抬高)",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 18.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
        ("R5_g20_cap90_top30", "g20 + 15~90 + Top30(激进:小+宽成长+分散)",
         {"np_cagr_min": 0.20, "mktcap_min_yi": 15.0, "mktcap_max_yi": 90.0, "rebalance_months": M, "top_n": 30}),
        ("R5_combo_cap90_top30", "g22 + 15~90 + Top30",
         {"np_cagr_min": 0.22, "mktcap_min_yi": 15.0, "mktcap_max_yi": 90.0, "rebalance_months": M, "top_n": 30}),
        ("R5_combo_pe50", "g22 + 15~100 + PE上限50(放宽估值天花板)",
         {"np_cagr_min": 0.22, "pe_max": 50.0, "mktcap_min_yi": 15.0, "mktcap_max_yi": 100.0, "rebalance_months": M, "top_n": 25}),
    ],
    # Round 6(卖出侧 + 财务质量增强): 选股侧参数已穷尽收敛于 15~100/g25/月度/Top25(+4.48%),
    # 本轮挖掘唯一未动的两个新维度——① 持有期个股止损(硬止损/移动止损,压回撤)
    # ② 财务质量过滤(资产负债率/经营现金流,剔脆弱+纸面利润,可能选出更稳健子集)。
    # base = 已锁定默认值(空 overrides),R6_base 应复现 +4.48% 作对照。
    "6": [
        ("R6_base", "锁定默认值对照(15~100/g25/月度/Top25,应=+4.48%)", {}),
        ("R6_stop15", "硬止损 -15%", {"stop_loss_pct": 0.15}),
        ("R6_stop20", "硬止损 -20%", {"stop_loss_pct": 0.20}),
        ("R6_stop25", "硬止损 -25%", {"stop_loss_pct": 0.25}),
        ("R6_trail20", "移动止损 回撤20%", {"trailing_stop_pct": 0.20}),
        ("R6_trail25", "移动止损 回撤25%", {"trailing_stop_pct": 0.25}),
        ("R6_trail30", "移动止损 回撤30%", {"trailing_stop_pct": 0.30}),
        ("R6_debt60", "资产负债率≤60%", {"max_debt_ratio": 0.60}),
        ("R6_debt50", "资产负债率≤50%", {"max_debt_ratio": 0.50}),
        ("R6_cfo_pos", "经营现金流为正(CFO/NP≥0.01)", {"min_cfo_np_ratio": 0.01}),
        ("R6_cfo50", "现金含量 CFO/NP≥0.5", {"min_cfo_np_ratio": 0.50}),
        ("R6_quality_combo", "负债≤60% + CFO为正(双质量过滤,无止损)",
         {"max_debt_ratio": 0.60, "min_cfo_np_ratio": 0.01}),
    ],
}

CSI300_CODE = "CSI300"  # v_a_index 里沪深300 的 _symbol 标识


def _pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def _benchmark_annualized(start: str, end: str):
    """沪深300 区间年化收益率(基准对比)。视图缺失/数据不足返 None。"""
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
        d0 = str(df["date"].iloc[0])[:10]
        d1 = str(df["date"].iloc[-1])[:10]
        from datetime import date as _date

        days = (_date.fromisoformat(d1) - _date.fromisoformat(d0)).days
        years = days / 365.25 if days > 0 else 0
        annual = (1 + total) ** (1 / years) - 1 if years > 0 else None
        return annual, total
    except Exception as e:
        log.warning("benchmark CSI300 failed: %s", e)
        return None, None


def _run_one(sliced, tag, note, overrides):
    strat = LynchFastGrowersStrategy(param_overrides=overrides)
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


def _write(summaries, round_tag, bench_annual, bench_total):
    out_json = OUT_DIR / f"lynch_fg_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# 林奇·快速增长型 参数探索 Round {round_tag}",
        "",
        f"区间 {START} → {END} | 全 A 股 | 完成 {len(ok)}/{len(summaries)}",
        f"基准 沪深300:年化 {_pct(bench_annual)} / 总收益 {_pct(bench_total)}",
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
    (OUT_DIR / f"lynch_fg_r{round_tag}_overview.md").write_text("\n".join(lines))


def _run_round(sliced, round_key, round_label, bench_annual, bench_total):
    """跑单轮所有 config(复用已切片的 bundle),增量写排行榜。"""
    configs = ROUNDS[round_key]
    summaries = []
    log.info(">>> Round %s: %d configs", round_key, len(configs))
    for tag, note, ov in configs:
        try:
            summaries.append(_run_one(sliced, tag, note, ov))
        except Exception as e:
            log.exception("[%s] FAILED: %s", tag, e)
            summaries.append({"tag": tag, "note": note, "error": str(e)})
        _write(summaries, round_label, bench_annual, bench_total)
    log.info("<<< DONE round %s -> exported/lynch_fg_r%s_overview.md",
             round_key, round_label)


def main():
    global START, END
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="smoke",
                    help="轮次号 (smoke | 1 | all)")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--label", default="", help="输出文件后缀(区分子区间跑)")
    args = ap.parse_args()

    if args.round == "all":
        round_keys = [k for k in ROUNDS.keys() if k != "smoke"]
    elif args.round in ROUNDS:
        round_keys = [args.round]
    else:
        log.error("unknown round %s; available: %s | all", args.round, list(ROUNDS))
        return

    START, END = args.start, args.end
    start, end = args.start, args.end

    growth_long.reset_annual_cache()
    st_filter.reset_st_cache()
    log.info("加载 A bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("A") or data_cache._load_market_blocking("A")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, start, end)
    log.info("sliced %d stocks iter[%d,%d] %s→%s", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx, start, end)

    bench_annual, bench_total = _benchmark_annualized(start, end)
    log.info("CSI300 基准: 年化=%s 总收益=%s", _pct(bench_annual), _pct(bench_total))

    t_all = time.time()
    for rk in round_keys:
        _run_round(sliced, rk, f"{rk}{args.label}", bench_annual, bench_total)
    log.info("ALL DONE rounds=%s (%s→%s) in %.0fs",
             round_keys, start, end, time.time() - t_all)


if __name__ == "__main__":
    main()
