"""林奇·困境反转型(Turnarounds)A 股策略参数探索 —— 找平均年化 ≈15%。

加载 A 股 bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜(含沪深300基准)。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

困境反转型 = 曾陷亏损/重挫、正从谷底爬出的公司(公司特质性,非行业景气)。排除金融
(去杠杆/FCFF 框架不适用,可选连地产)+ 低 PB 破净估值锚(刻意不卡 PE,规避市盈率悖论)
+ 反转信号(默认扭亏为盈 np_turn)+ 可选困境准入(曾亏损/重挫/ROE 低迷)+ 可选去杠杆
(资产负债率逐年下降,林奇"How is it going to survive?"核心)/ 现金流转正。择时靠调仓自然
轮出 + 可选移动止损。与快速/缓慢/稳健/周期四型互补。

🚨🚨 幸存者偏差在本类**最严重**:困境公司真实破产/退市/违约率远高于其它型,数据仅含当前
在市标的 → "死亡样本"系统性缺失,回测收益显著偏乐观,结论须打足折扣。
⚠️ ST/*ST 是最极端反转标的但被项目 ST 过滤剔除 → 本策略只覆盖"非 ST 困境股",结论须注明。

用法:
  # 先 smoke 验证端到端(选 2015-07~2019-01, 含 2015 股灾后修复 + 2016-18 供给侧扭亏, 后台跑):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_turnarounds/run_lynch_turnarounds_matrix.py --round smoke --start 2015-07-01 --end 2019-01-01 \
      > logs/lynch_tr_smoke.log 2>&1 &
  # 全期跑 Round 1(后台):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_turnarounds/run_lynch_turnarounds_matrix.py --round 1 > logs/lynch_tr_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本随策略迁入 experiments/lynch/lynch_turnarounds/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_tr")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long, st_filter
from services.backtest.strategies.experiments.lynch.lynch_turnarounds.lynch_turnarounds_strategy import (
    LynchTurnaroundsStrategy,
)

START = "2010-01-01"
END = "2026-06-01"

# 自闭环:回测产物(json/overview.md)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
# 策略默认: exclude_sectors=financial, pb≤2.0, use_pe_filter=False(市盈率悖论),
#   recovery_mode=np_turn(扭亏), distress_mode=none, roe 全关, dele_mode=none,
#   max_debt/min_cfo 全关, mktcap≥50亿, top20, pb升序(谷底优先), 月度调仓.
ROUNDS: dict[str, list] = {
    # smoke: 单配置, 仅验证端到端可跑通(配 2015-07~2019-01 扭亏窗口前台/后台跑)
    "smoke": [
        ("TR_smoke", "默认配置 smoke 验证", {}),
    ],
    # Round 1: 粗扫困境反转各主轴
    # (调仓频率 / 反转信号 / 行业排除 / PB 松紧 / 排序 / 集中度 / 困境准入预览 / 去杠杆预览 / 分散 / 止损)
    "1": [
        ("R1_base", "基线(排金融 pb≤2 np_turn top20 月度 pb排序 mktcap≥50)", {}),
        # —— 调仓频率(反转拐点须及时 catch vs A股低频惯例)——
        ("R1_quarter", "季度调仓", {"rebalance_months": [3, 6, 9, 12]}),
        ("R1_semiann", "半年调仓(6/12月)", {"rebalance_months": [6, 12]}),
        ("R1_annual_jun", "年度调仓(仅6月, 年报已披露)", {"rebalance_months": [6]}),
        # —— 反转信号(灵魂: 盈利从底部往上拐)——
        ("R1_rec_none", "无反转信号(纯低PB破净深价值)", {"recovery_mode": "none"}),
        ("R1_rec_improve", "反转=净利同比改善(含亏损收窄)", {"recovery_mode": "np_improve"}),
        ("R1_rec_rev", "反转=营收同比改善(更平滑)", {"recovery_mode": "rev_improve"}),
        ("R1_rec_roe", "反转=ROE回升", {"recovery_mode": "roe_recover"}),
        # —— 行业排除(困境可发生任何行业, 只排框架不适用者)——
        ("R1_excl_none", "不排除任何行业(含金融对照)", {"exclude_sectors": "none"}),
        ("R1_excl_fin_re", "排除金融+地产(地产幸存者偏差最重)", {"exclude_sectors": "financial_realestate"}),
        # —— PB 松紧(破净估值锚)——
        ("R1_pb15", "PB≤1.5(更破净)", {"pb_max": 1.5}),
        ("R1_pb3", "PB≤3.0(放宽)", {"pb_max": 3.0}),
        ("R1_pb_off", "不卡PB(仅排金融+扭亏)", {"pb_max": 0.0}),
        ("R1_pbmin03", "PB≥0.3(剔退市边缘极低PB陷阱)", {"pb_min": 0.3}),
        # —— 排序 ——
        ("R1_sort_rec", "按反转强度降序", {"sort_by": "recovery"}),
        ("R1_sort_comp", "composite(低PB+强反转)", {"sort_by": "composite"}),
        # —— 集中度(困境股个股波动大, 分散尤为重要)——
        ("R1_top10", "Top10集中", {"top_n": 10}),
        ("R1_top30", "Top30分散", {"top_n": 30}),
        # —— 困境准入预览(把反转从普通低估股里区分)——
        ("R1_distress_loss", "困境准入: 近3年曾亏损", {"distress_mode": "prior_loss"}),
        ("R1_distress_dd", "困境准入: 净利曾从峰值回撤≥50%", {"distress_mode": "np_drawdown"}),
        # —— 去杠杆预览(林奇存活性检验)——
        ("R1_dele_down", "要求资产负债率较上年下降", {"dele_mode": "debt_down"}),
        # —— 分散 / 回撤压制 ——
        ("R1_sec2", "每行业≤2(分散)", {"require_industry": True, "max_per_sector": 2}),
        ("R1_trail25", "25%移动止损", {"trailing_stop_pct": 0.25}),
    ],
    # Round 2: 回撤压制 —— 困境股个股波动/破产风险大, 止损尤为相关。锚点 = R1 最佳(待 R1 结果确定后更新此注释)。
    # 暂以 base 为锚探索止损家族(trail 甜点 + 硬止损 + 组合), R1 出结果后据实际锚点微调。
    "2": [
        ("R2_base", "R1 锚点占位(base, 待 R1 更新)", {}),
        ("R2_trail30", "30%移动止损", {"trailing_stop_pct": 0.30}),
        ("R2_trail25", "25%移动止损", {"trailing_stop_pct": 0.25}),
        ("R2_trail20", "20%移动止损", {"trailing_stop_pct": 0.20}),
        ("R2_trail15", "15%移动止损(测紧边界)", {"trailing_stop_pct": 0.15}),
        ("R2_hard20", "20%硬止损", {"stop_loss_pct": 0.20}),
        ("R2_hard25", "25%硬止损", {"stop_loss_pct": 0.25}),
        ("R2_trail25_hard20", "移动25%+硬20%(双保险)", {"trailing_stop_pct": 0.25, "stop_loss_pct": 0.20}),
        ("R2_regime30_200", "熊市降至3成仓(沪深300 MA200)", {"risk_off_exposure": 0.3, "regime_ma_days": 200}),
    ],
    # Round 3: 市值带 —— 周期型经验: 市值带是击穿天花板的关键杠杆(小盘超额, 但幸存者偏差/滑点高须警惕)。
    # 锚点 = R1+R2 最佳(待更新)。以 base+trail25 为暂定锚探市值带。
    "3": [
        ("R3_anchor", "R1+R2 锚点占位(base+trail25, 待更新)", {"trailing_stop_pct": 0.25}),
        ("R3_band_30_80", "市值 30~80亿(小盘困境)", {"trailing_stop_pct": 0.25, "mktcap_min_yi": 30.0, "mktcap_max_yi": 80.0}),
        ("R3_band_50_100", "市值 50~100亿", {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0}),
        ("R3_band_50_150", "市值 50~150亿(更宽, 抗过拟合)", {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 150.0}),
        ("R3_band_70_130", "市值 70~130亿(中枢右移, 抗幸存者)", {"trailing_stop_pct": 0.25, "mktcap_min_yi": 70.0, "mktcap_max_yi": 130.0}),
        ("R3_min30", "仅下限≥30亿(放开上限)", {"trailing_stop_pct": 0.25, "mktcap_min_yi": 30.0}),
        ("R3_min100", "仅下限≥100亿(中大盘, 抗幸存者)", {"trailing_stop_pct": 0.25, "mktcap_min_yi": 100.0}),
    ],
    # Round 4: 资产负债表存活性(林奇困境反转核心)—— 去杠杆 + 现金流转正 + 负债率上限。
    # 锚点 = R1~R3 最佳(待更新)。以 base 为暂定锚, 单加/组合资产负债表因子。
    "4": [
        ("R4_anchor", "R1~R3 锚点占位(base, 待更新)", {}),
        ("R4_dele_down", "去杠杆: 负债率较上年下降", {"dele_mode": "debt_down"}),
        ("R4_dele_pct2", "去杠杆: 负债率降≥2个百分点", {"dele_mode": "debt_down_pct", "dele_min_drop": 0.02}),
        ("R4_dele_pct5", "去杠杆: 负债率降≥5个百分点(强去杠杆)", {"dele_mode": "debt_down_pct", "dele_min_drop": 0.05}),
        ("R4_dele_lb3", "去杠杆: 较前2年下降(dele_lookback=3)", {"dele_mode": "debt_down", "dele_lookback": 3}),
        ("R4_cfo_pos", "经营现金流为正(CFO/NP≥0.01)", {"min_cfo_np_ratio": 0.01}),
        ("R4_debt70", "资产负债率≤70%(剔高杠杆易破产)", {"max_debt_ratio": 0.70}),
        ("R4_debt60", "资产负债率≤60%", {"max_debt_ratio": 0.60}),
        ("R4_survive", "存活组合: 去杠杆 + CFO正 + 负债率≤70%", {"dele_mode": "debt_down", "min_cfo_np_ratio": 0.01, "max_debt_ratio": 0.70}),
    ],
    # Round 5: 困境准入变体 + 行业分散 —— 定义性门槛调优 + 分散/排除收敛定稿。
    # 锚点 = R1~R4 最佳(待更新)。全期跑完后另起 champ 三子区间复跑防过拟合。
    "5": [
        ("R5_anchor", "R1~R4 锚点占位(base, 待更新)", {}),
        ("R5_distress_loss", "困境准入: 近3年曾亏损", {"distress_mode": "prior_loss"}),
        ("R5_distress_loss_lb5", "困境准入: 近5年曾亏损", {"distress_mode": "prior_loss", "distress_lookback": 5}),
        ("R5_distress_lowroe", "困境准入: 曾ROE≤2%(深度低迷)", {"distress_mode": "prior_low_roe", "distress_roe_max": 2.0}),
        ("R5_distress_dd50", "困境准入: 净利曾回撤≥50%", {"distress_mode": "np_drawdown", "distress_np_drop_pct": 50.0}),
        ("R5_distress_dd70", "困境准入: 净利曾回撤≥70%(更重挫)", {"distress_mode": "np_drawdown", "distress_np_drop_pct": 70.0}),
        ("R5_sec2", "每行业≤2(分散压回撤)", {"require_industry": True, "max_per_sector": 2}),
        ("R5_sec3", "每行业≤3(温和分散)", {"require_industry": True, "max_per_sector": 3}),
        ("R5_excl_fin_re", "排除金融+地产(诚实变体, 幸存者偏差最轻)", {"exclude_sectors": "financial_realestate"}),
    ],
    # champ: 子区间稳健性检验(过拟合审计)。用 --label p1/p2/p3 + --start/--end 三段跑:
    #   p1 2010-01~2016-01(熊/震荡)、p2 2016-01~2021-01(供给侧+商品牛, 扭亏黄金期)、p3 2021-01~2026-06。
    #   全样本冠军与稳健基线并排放三段, 若冠军仅在某段大胜其余崩 → 坐实过拟合。
    #   ⚠️ 具体冠军配置待 R1~R5 定稿后填入(现为占位, 与周期型一致的审计流程)。
    "champ": [
        ("CH_base", "朴素基线: base(全域)", {}),
        ("CH_base_trail25", "base + trail25", {"trailing_stop_pct": 0.25}),
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
    strat = LynchTurnaroundsStrategy(param_overrides=overrides)
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
    out_json = OUT_DIR / f"lynch_tr_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# 林奇·困境反转型 参数探索 Round {round_tag}",
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
    (OUT_DIR / f"lynch_tr_r{round_tag}_overview.md").write_text("\n".join(lines))


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
    log.info("<<< DONE round %s -> exported/lynch_tr_r%s_overview.md",
             round_key, round_label)


def main():
    global START, END
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="smoke",
                    help="轮次号 (smoke | 1 | 2 | 3 | 4 | 5 | champ | all)")
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
    balance_long.reset_balance_cache()
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
