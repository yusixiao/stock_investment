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
# R11 全期冠军基座(进取+仅龙头+每行业≤2 = 25.77%);R14 在其上扫排序×阈值
BASE_R14 = {**BASE8, "top_n": 12, "trend_ma_days": 90,
            "require_industry": True, "max_per_sector": 2}
# R17 锁定的最优选股内核:BASE_R14 + g25(净利 CAGR≥25%,唯一跨 4 窗口 4/4 的成长过滤)
BASE_G25 = {**BASE_R14, "np_cagr_min": 0.25}
# R21 全期/H1/H2/切片全面冠军:BASE_R14 + pe_max=15(np_cagr_min 默认 0.15)
CHAMPION_PE15 = {**BASE_R14, "pe_max": 15.0}
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
    # Round 14: 在全期冠军基座(agg_ind_sec2=Top12+趋势90+仅龙头+每行业≤2=25.77%)上
    #   交叉探索「排序键」×「因子阈值」——行业约束固定,看能否在冠军上再榨 edge / 改善风险调整收益
    #   (R13 市场择时需多轮对比,单列;此轮不涉新数据)
    "14": [
        ("R14_base", "基座 agg_ind_sec2(peg升序排序)", BASE_R14),
        # --- 维度①:排序键(行业约束基座上换 sort_by)---
        ("R14_sortG", "+成长降序排序", {**BASE_R14, "sort_by": "growth"}),
        ("R14_sortC", "+复合排序(peg+growth rank)", {**BASE_R14, "sort_by": "composite"}),
        ("R14_garpmom", "+GARP×动量复合排序(6月)",
         {**BASE_R14, "momentum_days": 120, "sort_by": "garp_mom"}),
        ("R14_sortmom6", "+6月动量降序排序(追强)",
         {**BASE_R14, "momentum_days": 120, "sort_by": "momentum"}),
        # --- 维度②:因子阈值(基座 peg 排序 + 收紧阈值)---
        ("R14_roe15", "+ROE≥15(质量)", {**BASE_R14, "roe_min": 15.0}),
        ("R14_roe20", "+ROE≥20(强质量)", {**BASE_R14, "roe_min": 20.0}),
        ("R14_g20", "+净利CAGR≥20(强成长)", {**BASE_R14, "np_cagr_min": 0.20}),
        ("R14_peg10", "+PEG≤1.0(更便宜)", {**BASE_R14, "peg_max": 1.0}),
        ("R14_pegfloor", "+PEG≥0.4(剔超低陷阱)", {**BASE_R14, "peg_min": 0.4}),
        ("R14_pe25", "+PE≤25(防泡沫)", {**BASE_R14, "pe_max": 25.0}),
        # --- 维度③:排序×阈值交叉(最优组合候选)---
        ("R14_sortC_roe15", "复合排序+ROE15",
         {**BASE_R14, "sort_by": "composite", "roe_min": 15.0}),
        ("R14_garpmom_roe15", "GARP×动量+ROE15",
         {**BASE_R14, "momentum_days": 120, "sort_by": "garp_mom", "roe_min": 15.0}),
    ],
    # Round 15: R14 赢家的样本外稳健性验证(配 --start/--end 跑 full/H1/H2)
    #   验证 PEG≤1.0(27.27% 最高)、PE≤25(Sharpe 0.79 最佳)不是单段过拟合,
    #   并测两种"便宜度"过滤(peg10/pe25)及 peg10+g20 是否可叠加。
    #   ROE/PEG 地板已在 R14 证实反噬,不纳入。
    "15": [
        ("R15_base", "基座 agg_ind_sec2(参照)", BASE_R14),
        ("R15_peg10", "PEG≤1.0(R14 最高收益)", {**BASE_R14, "peg_max": 1.0}),
        ("R15_pe25", "PE≤25(R14 最佳 Sharpe)", {**BASE_R14, "pe_max": 25.0}),
        ("R15_g20", "净利CAGR≥20(R14 次高)", {**BASE_R14, "np_cagr_min": 0.20}),
        ("R15_peg10_pe25", "PEG≤1.0+PE≤25(双便宜度叠加)",
         {**BASE_R14, "peg_max": 1.0, "pe_max": 25.0}),
        ("R15_peg10_g20", "PEG≤1.0+净利CAGR≥20(便宜×强成长)",
         {**BASE_R14, "peg_max": 1.0, "np_cagr_min": 0.20}),
    ],
    # Round 16: 真 walk-forward —— 杜绝 selection bias 的样本外检验
    #   方法:用此【先验定义】的候选网格(不靠全期结果挑),在 H1(--start 2010 --end 2018)
    #   训练段排名 → 机械选出 H1 冠军 → 读它在 H2(--start 2018 --end 2026)测试段的表现。
    #   H2 全程不参与选参。若 H1 冠军在 H2 仍强 = 真 edge;若崩 = 坐实过拟合。
    #   网格沿 GARP 经济轴铺开(成长/便宜度/集中度/排序),各轴独立 + 少量交叉。
    "16": [
        ("R16_base", "基座 agg_ind_sec2(参照)", BASE_R14),
        # 轴①:成长阈值梯度
        ("R16_g15", "净利CAGR≥15", {**BASE_R14, "np_cagr_min": 0.15}),
        ("R16_g20", "净利CAGR≥20", {**BASE_R14, "np_cagr_min": 0.20}),
        ("R16_g25", "净利CAGR≥25", {**BASE_R14, "np_cagr_min": 0.25}),
        # 轴②:便宜度阈值梯度
        ("R16_peg10", "PEG≤1.0", {**BASE_R14, "peg_max": 1.0}),
        ("R16_peg15", "PEG≤1.5", {**BASE_R14, "peg_max": 1.5}),
        ("R16_pe20", "PE≤20", {**BASE_R14, "pe_max": 20.0}),
        ("R16_pe25", "PE≤25", {**BASE_R14, "pe_max": 25.0}),
        # 轴③:集中度
        ("R16_t10", "Top10(更集中)", {**BASE_R14, "top_n": 10}),
        ("R16_t15", "Top15(更分散)", {**BASE_R14, "top_n": 15}),
        # 轴④:排序键
        ("R16_sortC", "复合排序(peg+growth rank)", {**BASE_R14, "sort_by": "composite"}),
        # 轴⑤:少量经济上合理的交叉
        ("R16_g20_peg15", "成长≥20 + PEG≤1.5", {**BASE_R14, "np_cagr_min": 0.20, "peg_max": 1.5}),
        ("R16_g20_pe25", "成长≥20 + PE≤25", {**BASE_R14, "np_cagr_min": 0.20, "pe_max": 25.0}),
        ("R16_sortC_g20", "复合排序 + 成长≥20",
         {**BASE_R14, "sort_by": "composite", "np_cagr_min": 0.20}),
    ],
    # Round 17: 成长阈值梯度的尾部探测(配 4 窗口 P1-P4 跑)
    #   R16/R17 矩阵已证 g25 跨 4 窗口 4/4 全胜、g20 仅 2/4(擦边)。
    #   此轮把成长轴从 g25 继续往上延伸(g30/g35),看超额是否【单调向上】
    #   还是 g25 后见顶回落(过度收紧→样本太少→噪声/反噬)。
    #   base/g20/g25 重跑用于在同一张表内对齐参照。
    "17": [
        ("R17_base", "基座 agg_ind_sec2(参照)", BASE_R14),
        ("R17_g20", "净利CAGR≥20", {**BASE_R14, "np_cagr_min": 0.20}),
        ("R17_g25", "净利CAGR≥25", {**BASE_R14, "np_cagr_min": 0.25}),
        ("R17_g30", "净利CAGR≥30", {**BASE_R14, "np_cagr_min": 0.30}),
        ("R17_g35", "净利CAGR≥35", {**BASE_R14, "np_cagr_min": 0.35}),
    ],
    # Round 18: 在 R17 锁定的最优内核(BASE_G25)上叠加 HSI 市场 regime 择时,
    #   目标 = 降回撤 + (尽量)提收益。每月检查 HSI regime,risk-off 时缩仓。
    #   3 信号(收盘>MA200 / 收盘>MA120 / MA50>MA200 金叉)× 3 risk-off 仓位(0.5/0.3/0)。
    #   全部 PIT(只用 current_date 之前的 HSI);base_g25 为无择时参照。
    #   配 4 窗口 P1-P4(--start/--end)跑,看 regime 是否跨周期稳定降回撤而非只在某段生效。
    "18": [
        ("R18_base_g25", "无择时参照(BASE_G25)", BASE_G25),
        # 信号①:HSI 收盘 > MA200(经典)
        ("R18_ma200_e50", "MA200择时·熊市半仓",
         {**BASE_G25, "regime_mode": "close_ma", "regime_ma_days": 200, "risk_off_exposure": 0.5}),
        ("R18_ma200_e30", "MA200择时·熊市3成仓",
         {**BASE_G25, "regime_mode": "close_ma", "regime_ma_days": 200, "risk_off_exposure": 0.3}),
        ("R18_ma200_e0", "MA200择时·熊市空仓",
         {**BASE_G25, "regime_mode": "close_ma", "regime_ma_days": 200, "risk_off_exposure": 0.0}),
        # 信号②:HSI 收盘 > MA120(与个股趋势 90/120 同哲学)
        ("R18_ma120_e50", "MA120择时·熊市半仓",
         {**BASE_G25, "regime_mode": "close_ma", "regime_ma_days": 120, "risk_off_exposure": 0.5}),
        ("R18_ma120_e30", "MA120择时·熊市3成仓",
         {**BASE_G25, "regime_mode": "close_ma", "regime_ma_days": 120, "risk_off_exposure": 0.3}),
        ("R18_ma120_e0", "MA120择时·熊市空仓",
         {**BASE_G25, "regime_mode": "close_ma", "regime_ma_days": 120, "risk_off_exposure": 0.0}),
        # 信号③:HSI MA50 > MA200(金叉/死叉,更平滑)
        ("R18_cross_e50", "金叉择时·熊市半仓",
         {**BASE_G25, "regime_mode": "ma_cross", "regime_fast_ma": 50, "regime_slow_ma": 200, "risk_off_exposure": 0.5}),
        ("R18_cross_e30", "金叉择时·熊市3成仓",
         {**BASE_G25, "regime_mode": "ma_cross", "regime_fast_ma": 50, "regime_slow_ma": 200, "risk_off_exposure": 0.3}),
        ("R18_cross_e0", "金叉择时·熊市空仓",
         {**BASE_G25, "regime_mode": "ma_cross", "regime_fast_ma": 50, "regime_slow_ma": 200, "risk_off_exposure": 0.0}),
    ],
    # Round 19: 在 BASE_G25 上做个股波动率加权(不叠指数择时),目标"降回撤不伤收益"。
    # 基线 EW(1/N) + invvol/invvar × lookback{60,120,252},单股封顶 2.5×等权。
    "19": [
        ("R19_ew", "等权 1/N 参照(BASE_G25)", BASE_G25),
        ("R19_invvol_60", "反波动率加权·60日",
         {**BASE_G25, "weight_scheme": "invvol", "vol_lookback": 60, "weight_cap_mult": 2.5}),
        ("R19_invvol_120", "反波动率加权·120日",
         {**BASE_G25, "weight_scheme": "invvol", "vol_lookback": 120, "weight_cap_mult": 2.5}),
        ("R19_invvol_252", "反波动率加权·252日",
         {**BASE_G25, "weight_scheme": "invvol", "vol_lookback": 252, "weight_cap_mult": 2.5}),
        ("R19_invvar_60", "反方差加权·60日",
         {**BASE_G25, "weight_scheme": "invvar", "vol_lookback": 60, "weight_cap_mult": 2.5}),
        ("R19_invvar_120", "反方差加权·120日",
         {**BASE_G25, "weight_scheme": "invvar", "vol_lookback": 120, "weight_cap_mult": 2.5}),
         ("R19_invvar_252", "反方差加权·252日",
          {**BASE_G25, "weight_scheme": "invvar", "vol_lookback": 252, "weight_cap_mult": 2.5}),
    ],
    # Round 21: 便宜度梯度【下沿】探测(2026-06-13)。历史只测过 PE≤25/20,
    #   全期+H1/H2 都证 PE≤20 是冠军且越便宜越好(35→25→20 单调向上)。
    #   此轮把 pe_max 继续往下压(15/10),看下沿是【平台】(稳健宽带)
    #   还是【悬崖】(港股低 PE 多价值陷阱/周期顶,压太低反而筛掉好成长股)。
    #   pe25/pe20 为同表对齐参照。均在 BASE_R14(np_cagr_min 默认 0.15)上。
    "21": [
        ("R21_base", "基座 BASE_R14(无便宜度过滤,pe_max=35)", BASE_R14),
        ("R21_pe25", "PE≤25(参照)", {**BASE_R14, "pe_max": 25.0}),
        ("R21_pe20", "PE≤20(冠军参照)", {**BASE_R14, "pe_max": 20.0}),
        ("R21_pe15", "PE≤15", {**BASE_R14, "pe_max": 15.0}),
        ("R21_pe10", "PE≤10", {**BASE_R14, "pe_max": 10.0}),
    ],
    # Round 22: 在【新冠军 CHAMPION_PE15】基座上重验个股波动率加权(2026-06-14)。
    #   R19 曾在旧基座 BASE_G25(npCAGR≥25)上测过,invvol/invvar 与等权几乎打平
    #   (invvol_252 微胜 EW),但基座已变(冠军=pe15/npCAGR默认0.15),需在新内核重验。
    #   目标:看反波动率/反方差加权能否在不伤收益下降回撤/提 Sharpe。
    #   单股封顶 2.5×等权(=20.83%),与 R19 一致;lookback 扫 {60,120,252}。
    "22": [
        ("R22_ew", "等权 1/N 参照(CHAMPION_PE15)", CHAMPION_PE15),
        ("R22_invvol_60", "反波动率加权·60日",
         {**CHAMPION_PE15, "weight_scheme": "invvol", "vol_lookback": 60, "weight_cap_mult": 2.5}),
        ("R22_invvol_120", "反波动率加权·120日",
         {**CHAMPION_PE15, "weight_scheme": "invvol", "vol_lookback": 120, "weight_cap_mult": 2.5}),
        ("R22_invvol_252", "反波动率加权·252日",
         {**CHAMPION_PE15, "weight_scheme": "invvol", "vol_lookback": 252, "weight_cap_mult": 2.5}),
        ("R22_invvar_60", "反方差加权·60日",
         {**CHAMPION_PE15, "weight_scheme": "invvar", "vol_lookback": 60, "weight_cap_mult": 2.5}),
        ("R22_invvar_120", "反方差加权·120日",
         {**CHAMPION_PE15, "weight_scheme": "invvar", "vol_lookback": 120, "weight_cap_mult": 2.5}),
        ("R22_invvar_252", "反方差加权·252日",
         {**CHAMPION_PE15, "weight_scheme": "invvar", "vol_lookback": 252, "weight_cap_mult": 2.5}),
    ],
    # Round 23: 冠军 CHAMPION_PE15 关键参数 plateau / 敏感性检查(2026-06-14)。
    #   目的:确认冠军每个关键参数落在【平台】(邻域平滑、稳健)而非【尖峰】(过拟合)。
    #   方法 = 单变量扫描(one-at-a-time):每次只动一个参数,其余固定在冠军值
    #   (top_n=12 / trend_ma_days=90 / max_per_sector=2 / peg_max=1.5 / pe_max=15)。
    #   R23_champion 为锚点(=CHAMPION_PE15),各 sweep 已剔除冠军值避免重复跑。
    #   pe_max 粗梯度(10/15/20/25/35)已在 R21 测过,此处补峰附近细点 12/13/18。
    "23": [
        ("R23_champion", "锚点 CHAMPION_PE15(t12/ma90/sec2/peg1.5/pe15)", CHAMPION_PE15),
        # --- top_n 邻域 ---
        ("R23_top8", "top_n=8(更集中)", {**CHAMPION_PE15, "top_n": 8}),
        ("R23_top10", "top_n=10", {**CHAMPION_PE15, "top_n": 10}),
        ("R23_top15", "top_n=15", {**CHAMPION_PE15, "top_n": 15}),
        ("R23_top20", "top_n=20(更分散)", {**CHAMPION_PE15, "top_n": 20}),
        # --- trend_ma_days 邻域 ---
        ("R23_ma60", "trend_ma=60", {**CHAMPION_PE15, "trend_ma_days": 60}),
        ("R23_ma120", "trend_ma=120", {**CHAMPION_PE15, "trend_ma_days": 120}),
        ("R23_ma150", "trend_ma=150", {**CHAMPION_PE15, "trend_ma_days": 150}),
        # --- max_per_sector 邻域 ---
        ("R23_sec1", "max_per_sector=1(每行业仅1只)", {**CHAMPION_PE15, "max_per_sector": 1}),
        ("R23_sec3", "max_per_sector=3", {**CHAMPION_PE15, "max_per_sector": 3}),
        ("R23_sec4", "max_per_sector=4", {**CHAMPION_PE15, "max_per_sector": 4}),
        # --- peg_max 邻域 ---
        ("R23_peg10", "peg_max=1.0", {**CHAMPION_PE15, "peg_max": 1.0}),
        ("R23_peg125", "peg_max=1.25", {**CHAMPION_PE15, "peg_max": 1.25}),
        ("R23_peg175", "peg_max=1.75", {**CHAMPION_PE15, "peg_max": 1.75}),
        ("R23_peg20", "peg_max=2.0", {**CHAMPION_PE15, "peg_max": 2.0}),
        # --- pe_max 峰附近细点(粗梯度 10/15/20/25/35 见 R21) ---
        ("R23_pe12", "pe_max=12", {**CHAMPION_PE15, "pe_max": 12.0}),
        ("R23_pe13", "pe_max=13", {**CHAMPION_PE15, "pe_max": 13.0}),
        ("R23_pe18", "pe_max=18", {**CHAMPION_PE15, "pe_max": 18.0}),
    ],
    # Round 24: 便宜度族 OOS 对比(2026-06-14)。用户问 pe18/pe20 邻域更平滑是否
    #   在样本外也更稳。R21 的 H1/H2 已有 pe20/pe15,缺 pe18。本轮在 H1(2010-2018
    #   训练段)/ H2(2018-2026 封存测试段)各跑一次,含 pe20/pe15 作区间对齐校验
    #   (若跑出的 pe20/pe15 与 R21_H{1,2} 一致 → 切片对齐,pe18 结果可信)。
    #   跑法:--round 24 --start 2010-01-01 --end 2018-01-01 --label _H1
    #        --round 24 --start 2018-01-01 --end 2026-06-01 --label _H2
    "24": [
        ("R24_base", "基座 BASE_R14(pe_max=35,无便宜度过滤)", BASE_R14),
        ("R24_pe20", "PE≤20(校验对齐 R21)", {**BASE_R14, "pe_max": 20.0}),
        ("R24_pe18", "PE≤18(新增,平台候选)", {**BASE_R14, "pe_max": 18.0}),
        ("R24_pe15", "PE≤15(冠军,校验对齐 R21)", {**BASE_R14, "pe_max": 15.0}),
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


def _run_round(sliced, round_key, round_label):
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
        _write(summaries, round_label)
    log.info("<<< DONE round %s -> exported/hk_garp_r%s_overview.md",
             round_key, round_label)


def main():
    global START, END
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="1",
                    help="轮次号,或 'all' 一次跑全部 R1-R19(共用一次 bundle 加载)")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--label", default="", help="输出文件后缀(区分子区间跑)")
    args = ap.parse_args()

    if args.round == "all":
        round_keys = list(ROUNDS.keys())
    elif args.round in ROUNDS:
        round_keys = [args.round]
    else:
        log.error("unknown round %s; available: %s | all", args.round, list(ROUNDS))
        return

    START, END = args.start, args.end
    start, end = args.start, args.end

    growth_hk.reset_cache()
    hk_industry.reset_cache()
    log.info("加载 HK bundle ...")
    t0 = time.time()
    bundle = data_cache.get_market("HK") or data_cache._load_market_blocking("HK")
    log.info("bundle loaded %d stocks in %.1fs", len(bundle.stock_data), time.time() - t0)
    sliced = data_cache.slice_bundle(bundle, None, start, end)
    log.info("sliced %d stocks iter[%d,%d] %s→%s", len(sliced.stock_data),
             sliced.iter_start_idx, sliced.iter_end_idx, start, end)

    t_all = time.time()
    for rk in round_keys:
        _run_round(sliced, rk, f"{rk}{args.label}")
    log.info("ALL DONE rounds=%s (%s→%s) in %.0fs",
             round_keys, start, end, time.time() - t_all)


if __name__ == "__main__":
    main()
