"""林奇·稳健增长型(Stalwarts)A 股策略参数探索 —— 找平均年化 ≈15%。

加载 A 股 bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜(含沪深300基准)。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

稳健增长型 = 大型成熟蓝筹 + 净利/营收稳健中速增长(CAGR∈[10%,15%])+ PEG≤1.5 +
可选 TTM 股息率门槛。与"快速增长型(小盘高增)""缓慢增长型(高股息≤8%增)"互补。

用法:
  # 先 smoke 验证端到端(短区间, 前台快跑):
  python backend/services/backtest/strategies/experiments/lynch/lynch_stalwarts/run_lynch_stalwarts_matrix.py --round smoke --start 2018-01-01 --end 2020-01-01
  # 全期跑 Round 1(后台):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_stalwarts/run_lynch_stalwarts_matrix.py --round 1 > logs/lynch_st_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本随策略迁入 experiments/lynch/lynch_stalwarts/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_st")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import growth_long
from services.backtest.strategies.utils import st_filter
from services.backtest.strategies.experiments.lynch.lynch_stalwarts.lynch_stalwarts_strategy import (
    LynchStalwartsStrategy,
)

START = "2010-01-01"
END = "2026-06-01"

# 自闭环:回测产物(json/overview.md)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

M = list(range(1, 13))  # 月度调仓

# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
# 策略默认: cagr∈[10%,15%], 营收CAGR≥5%, mktcap≥300亿(无上限), ROE≥12, pe≤30, peg≤1.5,
#           top20, peg升序, 月度调仓, 股息门槛关闭。
ROUNDS: dict[str, list] = {
    # smoke: 单配置, 仅验证端到端可跑通(配短区间前台跑)
    "smoke": [
        ("ST_smoke", "默认配置 smoke 验证", {}),
    ],
    # Round 1: 粗扫林奇稳健增长各主轴
    # (调仓频率 / 成长带 / 大市值下限 / 集中度 / PEG·PE 估值 / ROE 质量 / 股息 / 排序 / regime)
    "1": [
        ("R1_base", "默认基线(月度 cagr10-15 mktcap≥300 peg1.5 pe30 roe12 top20 peg排序)", {}),
        # —— 调仓频率(大盘低换手, 缓慢增长型曾验证半年最佳)——
        ("R1_quarter", "季度调仓", {"rebalance_months": [3, 6, 9, 12]}),
        ("R1_semiann", "半年调仓(6/12月)", {"rebalance_months": [6, 12]}),
        ("R1_annual_jun", "年度调仓(仅6月, 年报已披露)", {"rebalance_months": [6]}),
        # —— 成长带 ——
        ("R1_g_faithful", "成长带收窄至林奇原意 10~12%", {"np_cagr_min": 0.10, "np_cagr_max": 0.12}),
        ("R1_g_wide", "成长带放宽 8~20%(扩样本, 两端外探)", {"np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        # —— 大市值下限(稳健型核心:越大越稳)——
        ("R1_cap200", "市值下限放宽至200亿(扩样本)", {"mktcap_min_yi": 200.0}),
        ("R1_cap500", "市值下限抬至500亿(更大盘)", {"mktcap_min_yi": 500.0}),
        ("R1_cap1000", "市值下限抬至1000亿(超大盘龙头)", {"mktcap_min_yi": 1000.0}),
        # —— 集中度 ——
        ("R1_top10", "Top10 集中", {"top_n": 10}),
        ("R1_top30", "Top30 分散", {"top_n": 30}),
        # —— 估值纪律 ——
        ("R1_peg1", "PEG≤1.0(严格林奇核心)", {"peg_max": 1.0}),
        ("R1_pe20", "PE上限收紧至20(深度价值)", {"pe_max": 20.0}),
        # —— 质量 ——
        ("R1_roe15", "ROE≥15 强质量", {"roe_min": 15.0}),
        # —— 股息(稳健蓝筹防御性增强)——
        ("R1_div2", "叠加 TTM 股息率≥2%", {"min_div_yield": 0.02}),
        ("R1_div3", "叠加 TTM 股息率≥3%(高股息防御)", {"min_div_yield": 0.03}),
        # —— 排序 ——
        ("R1_sortG", "按成长降序排序", {"sort_by": "growth"}),
        # —— 沪深300 regime 择时(降回撤)——
        ("R1_regime30", "regime 熊市3成仓(200日线)", {"risk_off_exposure": 0.3, "regime_ma_days": 200}),
    ],
    # Round 2: 堆叠 R1 各独立赢家(此前均在 monthly 基线上单独测).
    # R1 学习: PEG≤1.0(+4.4pp 唯一超基准)/ 低频年度(+2.9pp)/ 成长带避开10-15%(10-12或8-20更优)/
    #          股息≥3%(回撤最低54%)/ 市值≥500亿; 失败: regime择时(-2.96%)·绝对PE≤20·集中Top10·月度季度换手.
    # 锚点 = 两强独立杠杆合并: PEG≤1.0 + 年度6月调仓; 再逐层叠加股息/市值/成长/集中度.
    "2": [
        ("R2_anchor", "双强合并: PEG≤1.0 + 年度6月调仓",
         {"peg_max": 1.0, "rebalance_months": [6]}),
        ("R2_anchor_semi", "PEG≤1.0 + 半年6/12调仓",
         {"peg_max": 1.0, "rebalance_months": [6, 12]}),
        ("R2_peg08", "PEG≤0.8 + 年度(再推估值纪律)",
         {"peg_max": 0.8, "rebalance_months": [6]}),
        ("R2_anchor_div3", "PEG≤1.0 + 年度 + 股息≥3%(防御)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03}),
        ("R2_anchor_cap500", "PEG≤1.0 + 年度 + 市值≥500亿",
         {"peg_max": 1.0, "rebalance_months": [6], "mktcap_min_yi": 500.0}),
        ("R2_anchor_g1012", "PEG≤1.0 + 年度 + 成长10~12%",
         {"peg_max": 1.0, "rebalance_months": [6], "np_cagr_min": 0.10, "np_cagr_max": 0.12}),
        ("R2_anchor_g820", "PEG≤1.0 + 年度 + 成长8~20%",
         {"peg_max": 1.0, "rebalance_months": [6], "np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        ("R2_def_stack", "防御栈: PEG≤1.0 + 年度 + 股息≥3% + 市值≥500亿",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "mktcap_min_yi": 500.0}),
        ("R2_full", "全赢家栈: PEG≤1.0 + 年度 + 股息≥3% + 500亿 + 成长10~12%",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "mktcap_min_yi": 500.0, "np_cagr_min": 0.10, "np_cagr_max": 0.12}),
        ("R2_full_g820", "全赢家栈(成长8~20%替代窄带)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "mktcap_min_yi": 500.0, "np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        ("R2_anchor_div3_g820", "PEG≤1.0 + 年度 + 股息≥3% + 成长8~20%(宽样本防御)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        ("R2_anchor_top12", "PEG≤1.0 + 年度 + Top12(集中 best-PEG)",
         {"peg_max": 1.0, "rebalance_months": [6], "top_n": 12}),
    ],
    # Round 3: R2 收敛出两个最优,核心矛盾 = 宽成长带(8-20%)买到 +1.5pp 收益但回撤 +22pp(周期股拖累).
    #   A 基(高收益): PEG≤1.0 + 年度6月 + 股息≥3% + 成长8-20% → 6.88% / 回撤57%
    #   B 基(低回撤): 同上但默认成长10-15%        → 5.36% / 回撤34.9% / Sharpe0.23
    # R2 还学到: 半年<年度; cap500 在任何组合都拖累收益; 窄带10-12%坍缩样本; top_n 不咬合(<12只).
    # R3 任务: 用未测杠杆(max_per_sector 行业分散 / 止损 / 更高股息)压 A 基 57% 回撤而不丢收益; 同时抬 B 基.
    "3": [
        # —— A 基(高收益,成长8-20%)压回撤 ——
        ("R3_A_sec3", "A基 + 每行业≤3(分散降回撤)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 3}),
        ("R3_A_sec2", "A基 + 每行业≤2(强分散,仿缓慢增长)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2}),
        ("R3_A_trail25", "A基 + 25%移动止损(锁利降回撤)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "trailing_stop_pct": 0.25}),
        ("R3_A_stop25", "A基 + 25%硬止损",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "stop_loss_pct": 0.25}),
        ("R3_A_div4", "A基 + 股息≥4%(更强防御)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.04,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        ("R3_A_div5", "A基 + 股息≥5%(极致高息)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.05,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        ("R3_A_composite", "A基 + composite 排序(peg+成长复合)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "sort_by": "composite"}),
        ("R3_A_peg08", "A基 + PEG≤0.8(宽成长上收紧估值)",
         {"peg_max": 0.8, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20}),
        ("R3_A_sec2_div4", "A基 + 每行业≤2 + 股息≥4%(双防御组合)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.04,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2}),
        ("R3_A_sec3_trail25", "A基 + 每行业≤3 + 25%移动止损",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 3, "trailing_stop_pct": 0.25}),
        # —— B 基(低回撤,默认成长10-15%)抬收益 ——
        ("R3_B_peg08", "B基 + PEG≤0.8",
         {"peg_max": 0.8, "rebalance_months": [6], "min_div_yield": 0.03}),
        ("R3_B_div4", "B基 + 股息≥4%",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.04}),
        ("R3_B_sec2", "B基 + 每行业≤2",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "require_industry": True, "max_per_sector": 2}),
        ("R3_B_g818", "B基 + 成长8-18%(适度放宽)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.18}),
    ],
    # Round 4: R3 大突破 —— 行业分散(max_per_sector)是最强杠杆,单调: 无cap 6.88% → ≤3 9.38% → ≤2 10.48%.
    #   高息低PEG宽成长池此前集中在银行/公用/地产 1-2 行业,分散后捕获更多价值名.
    #   其它学习: 移动止损25%削~15pp回撤(收益中性); 股息非单调(3%最优收益/5%极低回撤23%/4%最差);
    #             composite排序 +1.3pp; 宽成长(8-20)+行业cap 才是赢家组合; PEG≤0.8在宽成长上反伤.
    # C 基 = R3 冠军 A_sec2 = PEG≤1.0 + 年度6月 + 股息≥3% + 成长8-20% + 行业≤2.
    # R4 任务: 测更强分散(≤1)、收益增强(composite/更宽成长/更多持仓)、把移动止损叠到 sec2 上压回撤; 逼近 15%.
    "4": [
        # —— 分散强度 ——
        ("R4_sec1", "C基但每行业≤1(极致分散)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 1}),
        # —— 收益增强:composite 排序 ——
        ("R4_C_composite", "C基 + composite 排序",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "sort_by": "composite"}),
        ("R4_sec1_composite", "每行业≤1 + composite 排序",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 1, "sort_by": "composite"}),
        # —— 收益增强:更宽成长带 ——
        ("R4_C_g825", "C基 + 成长8-25%(上探高增)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.25, "require_industry": True, "max_per_sector": 2}),
        ("R4_C_g830", "C基 + 成长8-30%(更宽)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.30, "require_industry": True, "max_per_sector": 2}),
        ("R4_C_g525", "C基 + 成长5-25%(降下限扩样本)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.05, "np_cagr_max": 0.25, "require_industry": True, "max_per_sector": 2}),
        ("R4_C_comp_g825", "C基 + composite + 成长8-25%(双增强)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.25, "require_industry": True,
          "max_per_sector": 2, "sort_by": "composite"}),
        # —— 收益增强:持仓数 ——
        ("R4_C_top30", "C基 + Top30(分散后放更多名)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "top_n": 30}),
        ("R4_C_top15", "C基 + Top15(略集中)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "top_n": 15}),
        # —— 回撤压制:移动止损叠到 sec2 ——
        ("R4_C_trail25", "C基 + 25%移动止损",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "trailing_stop_pct": 0.25}),
        ("R4_C_trail20", "C基 + 20%移动止损(更紧)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "trailing_stop_pct": 0.20}),
        ("R4_C_trail30", "C基 + 30%移动止损(更松)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "trailing_stop_pct": 0.30}),
        ("R4_C_comp_trail25", "C基 + composite + 25%移动止损(收益+回撤双优)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True,
          "max_per_sector": 2, "sort_by": "composite", "trailing_stop_pct": 0.25}),
        # —— 低回撤变体:sec2 + 极致高息 ——
        ("R4_C_div5", "C基 + 股息≥5%(分散×高息,博极低回撤)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.05,
          "np_cagr_min": 0.08, "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2}),
    ],
    # Round 5: R4 锁定冠军 C基(sec2)=PEG≤1.0+年度6月+股息≥3%+成长8-20%+行业≤2 → 10.48%/回撤49.8%/Sharpe0.48.
    #   R4 还确认: 行业≤2 是分散最优(≤1 太稀疏); top_n 在[15,30]不咬合(过滤后池仅~10-15只);
    #             移动止损25%是甜点(20%太紧杀收益至2.8%); composite≈peg(略逊); 成长8-20最优(更宽噪声/更差);
    #             注: PEG≤1.0×成长≤20% ⇒ PE 天然≤20, 故 pe_max=30 不咬合, R5 不测 PE.
    # R5 攻未测结构性维度(均在 C基 sec2 上叠加), 重点 = 市值下限扫描(中盘成长更快, 或可推向15%, 但抬幸存者偏差).
    "5": [
        # —— 市值下限扫描(当前300亿;放低纳入中盘 stalwart)——
        ("R5_cap250", "C基 + 市值≥250亿",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
        ("R5_cap200", "C基 + 市值≥200亿",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 200.0}),
        ("R5_cap150", "C基 + 市值≥150亿(中盘)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 150.0}),
        ("R5_cap100", "C基 + 市值≥100亿(中小盘,慎幸存者偏差)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 100.0}),
        # —— 营收增长下限 ——
        ("R5_rev0", "C基 + 取消营收增长下限(纳入利润驱动/回购型)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "rev_cagr_min": 0.0}),
        ("R5_rev10", "C基 + 营收增长≥10%(量价齐升)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "rev_cagr_min": 0.10}),
        # —— 成长回看年数 ——
        ("R5_cagr2", "C基 + 成长回看2年(更近动量)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "cagr_years": 2}),
        ("R5_cagr5", "C基 + 成长回看5年(更长 track record)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "cagr_years": 5}),
        # —— ROE 质量门槛 ——
        ("R5_roe10", "C基 + ROE≥10(放宽质量)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "roe_min": 10.0}),
        ("R5_roe15", "C基 + ROE≥15(强质量)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "roe_min": 15.0}),
        # —— 调仓月份(此前仅测6月)——
        ("R5_reb4", "C基 + 4月调仓(年报季前)",
         {"peg_max": 1.0, "rebalance_months": [4], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2}),
        ("R5_reb9", "C基 + 9月调仓(半年报后)",
         {"peg_max": 1.0, "rebalance_months": [9], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2}),
        # —— 中盘成长动量组合 ——
        ("R5_cap150_cagr2", "C基 + 市值≥150亿 + 成长回看2年(中盘动量)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2,
          "mktcap_min_yi": 150.0, "cagr_years": 2}),
    ],
    # R5 定论: cap250 (11.24%/Sharpe0.52) 为收益+Sharpe 双冠; rev≥5%/cagr3yr/roe10-12/6月调仓 均已最优.
    # R6 任务: 不再盲目追高(过拟合风险已现, ~11% 接近 A 股 stalwart 现实上限), 转做稳健性 + 部署变体:
    #   ① cap250 邻域稳健性 (225/275, 确认非偶然尖点); ② 三大部署变体 (max收益/均衡/防御);
    #   ③ 最后两个收益增强探针 (更宽成长上限 / 唯一未测的 200日趋势过滤).
    # 冠军 D基 = cap250 sec2 = PEG≤1.0 + 年度6月 + 股息≥3% + 成长8-20% + 行业≤2 + 市值≥250亿.
    "6": [
        ("R6_D", "冠军 D基: cap250 sec2 (复跑校验, 应≈11.24%)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
        # —— cap250 邻域稳健性 ——
        ("R6_cap225", "D基 + 市值≥225亿(邻域稳健性)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 225.0}),
        ("R6_cap275", "D基 + 市值≥275亿(邻域稳健性)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 275.0}),
        # —— 部署变体:均衡(叠 25% 移动止损压回撤)——
        ("R6_D_trail25", "D基 + 25%移动止损(均衡变体)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0,
          "trailing_stop_pct": 0.25}),
        ("R6_D_comp_trail25", "D基 + composite + 25%移动止损(均衡+)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0,
          "sort_by": "composite", "trailing_stop_pct": 0.25}),
        # —— 部署变体:防御(股息≥5%, 期望极低回撤)——
        ("R6_D_div5", "D基 + 股息≥5%(防御变体)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.05, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
        # —— 收益增强探针 ——
        ("R6_D_g830", "D基 + 成长8-30%(放宽成长上限)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.30, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
        ("R6_D_trend200", "D基 + 200日趋势过滤(避价值陷阱, 唯一未测杠杆)",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0,
          "trend_ma_days": 200}),
    ],
    # 冠军 D基单配置, 供子区间稳健性验证 (配合 --start/--end/--label _p1.._p3, 检验非单一窗口驱动).
    "champ": [
        ("CHAMP", "冠军 cap250 sec2 子区间验证",
         {"peg_max": 1.0, "rebalance_months": [6], "min_div_yield": 0.03, "np_cagr_min": 0.08,
          "np_cagr_max": 0.20, "require_industry": True, "max_per_sector": 2, "mktcap_min_yi": 250.0}),
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
    strat = LynchStalwartsStrategy(param_overrides=overrides)
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
    out_json = OUT_DIR / f"lynch_st_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# 林奇·稳健增长型 参数探索 Round {round_tag}",
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
    (OUT_DIR / f"lynch_st_r{round_tag}_overview.md").write_text("\n".join(lines))


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
    log.info("<<< DONE round %s -> exported/lynch_st_r%s_overview.md",
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
