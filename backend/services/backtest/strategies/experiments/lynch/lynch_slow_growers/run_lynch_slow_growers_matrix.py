"""林奇·缓慢增长型(Slow Growers)A 股策略参数探索。

加载 A 股 bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜(含沪深300基准)。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

缓慢增长型 = 大盘成熟蓝筹 + 低速正增长 + 持续高分红 + 低 PE。绝对收益预期低于快速增长,
研判重点在**风险调整**(回撤/Sharpe)与是否稳定跑赢沪深300;且验证可迁移方法论中
「财务质量过滤对本类型可能正向有效」这一与快速增长相反的假设。

用法:
  # 先 smoke 验证端到端(短区间, 前台快跑):
  python backend/services/backtest/strategies/experiments/lynch/lynch_slow_growers/run_lynch_slow_growers_matrix.py --round smoke --start 2018-01-01 --end 2020-01-01
  # 全期跑 Round 1(后台):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_slow_growers/run_lynch_slow_growers_matrix.py --round 1 > logs/lynch_sg_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本随策略迁入 experiments/lynch/lynch_slow_growers/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_sg")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import growth_long
from services.backtest.strategies.utils import st_filter
from services.backtest.strategies.experiments.lynch.lynch_slow_growers.lynch_slow_growers_strategy import (
    LynchSlowGrowersStrategy,
)

START = "2010-01-01"
END = "2026-06-01"

# 自闭环:回测产物(json/overview.md)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

M = list(range(1, 13))  # 月度调仓

# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
# 策略默认: CAGR∈[0,8%], 连续分红≥5年, 股息率≥3%, mktcap≥200亿, PE≤25, 股息率降序, Top20, 月度调仓
ROUNDS: dict[str, list] = {
    # smoke: 单配置, 仅验证端到端可跑通(配短区间前台跑)
    "smoke": [
        ("SG_smoke", "默认配置 smoke 验证", {}),
    ],
    # Round 1: 粗扫缓慢增长各主轴 —— 排序键 / 股息率门槛 / 连续分红年数 / 市值带 /
    # PE 天花板 / 成长上限 / 分散度 / 调仓频率 / ROE 质量 / 质量过滤(反向假设预演)。
    # 目的: 验证类型骨架可选出合理组合, 并看哪些轴对缓慢增长最敏感。
    "1": [
        ("R1_base", "默认基线(大盘200+/CAGR0-8/连续分红5yr/股息率3%/PE25/股息率降序/Top20/月度)", {}),
        ("R1_sort_pe", "排序改 低PE升序", {"sort_by": "pe"}),
        ("R1_sort_composite", "排序改 股息率+低PE 复合", {"sort_by": "composite"}),
        ("R1_yield2", "股息率下限放宽至2%(扩样本)", {"min_div_yield": 0.02}),
        ("R1_yield4", "股息率下限收紧至4%(更高股息)", {"min_div_yield": 0.04}),
        ("R1_div3yr", "连续分红≥3年(放宽)", {"min_div_years": 3}),
        ("R1_mktcap100", "市值下限放宽至100亿(纳入中盘)", {"mktcap_min_yi": 100.0}),
        ("R1_mktcap300", "市值下限抬至300亿(纯大盘)", {"mktcap_min_yi": 300.0}),
        ("R1_pe15", "PE上限收紧至15(深度价值)", {"pe_max": 15.0}),
        ("R1_pe35", "PE上限放宽至35", {"pe_max": 35.0}),
        ("R1_capmax12", "成长上限放宽至12%(纳入稳健增长边缘)", {"np_cagr_max": 0.12}),
        ("R1_top30", "Top30 更分散", {"top_n": 30}),
        ("R1_quarter", "季度调仓(缓慢增长低换手)", {"rebalance_months": [3, 6, 9, 12]}),
        ("R1_annual", "年度调仓(仅5月)", {"rebalance_months": [5]}),
        ("R1_roe10", "ROE≥10 质量门槛", {"roe_min": 10.0}),
        ("R1_debt60", "资产负债率≤60%(预演:质量过滤反向假设)", {"max_debt_ratio": 0.60}),
    ],
    # Round 2: 组合 R1 胜出杠杆 + 测交互(铁律:不可朴素叠加,须对照组验)。
    # R1 结论: ①股息率≥4% 是唯一同时升收益+降回撤的杠杆(8.53%/32.59%);②大盘≥300亿升收益;
    # ③低PE排序 > 股息率降序排序(base 追最高息=价值陷阱);④集中(Top20)> 分散(Top30);
    # ⑤成长上限放宽至12%升收益但越界稳定增长型。本轮锚定 yield≥4%,解耦"高股息过滤 vs 排序",
    # 叠加 大盘/集中,并把股息率推更高(5/6%)、温和扩成长(≤10% 仍在型内)、试 regime 择时降回撤。
    "2": [
        ("R2_y4", "锚:股息率≥4%(R1冠军=本轮基线)", {"min_div_yield": 0.04}),
        ("R2_y5", "股息率≥5%(推防御杠杆更高)", {"min_div_yield": 0.05}),
        ("R2_y6", "股息率≥6%(极高股息,验样本是否过薄)", {"min_div_yield": 0.06}),
        ("R2_y4_sortpe", "股息率≥4% + 低PE排序(解耦:高股息=过滤,低PE=选股)",
         {"min_div_yield": 0.04, "sort_by": "pe"}),
        ("R2_y4_sortcomp", "股息率≥4% + 复合排序(股息+低PE)",
         {"min_div_yield": 0.04, "sort_by": "composite"}),
        ("R2_y4_cap300", "股息率≥4% + 市值≥300亿(叠加两胜出杠杆)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0}),
        ("R2_y4_top15", "股息率≥4% + Top15(集中)",
         {"min_div_yield": 0.04, "top_n": 15}),
        ("R2_y4_top10", "股息率≥4% + Top10(更集中)",
         {"min_div_yield": 0.04, "top_n": 10}),
        ("R2_y4_cap300_sortpe", "股息率≥4% + 市值≥300 + 低PE排序(三叠加)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "sort_by": "pe"}),
        ("R2_y4_cap300_sortpe_top15", "股息率≥4% + 市值≥300 + 低PE + Top15(全叠加)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "sort_by": "pe", "top_n": 15}),
        ("R2_y4_cap10", "股息率≥4% + 成长上限10%(温和扩成长,仍在缓慢增长型内)",
         {"min_div_yield": 0.04, "np_cagr_max": 0.10}),
        ("R2_y4_cap10_c300_pe", "股息率≥4% + 成长≤10% + 市值≥300 + 低PE(温和成长全叠加)",
         {"min_div_yield": 0.04, "np_cagr_max": 0.10, "mktcap_min_yi": 300.0, "sort_by": "pe"}),
        ("R2_y4_pe20", "股息率≥4% + PE≤20(高股息集内再收紧估值)",
         {"min_div_yield": 0.04, "pe_max": 20.0}),
        ("R2_y4_regime", "股息率≥4% + 沪深300 MA200 熊市半仓(择时降回撤)",
         {"min_div_yield": 0.04, "risk_off_exposure": 0.5}),
        ("R2_y5_pe_cap300", "股息率≥5% + 低PE + 市值≥300(更高股息全叠加)",
         {"min_div_yield": 0.05, "sort_by": "pe", "mktcap_min_yi": 300.0}),
    ],
    # Round 3: yield-sort 重验全叠加 + 类型边界对照 + 围绕甜点精调。
    # R2 结论: ①股息≥4% 甜点(3/5/6 更差);②市值≥300 +0.9pp 收益但 +5pp 回撤;
    # ③Top15 集中甜点(>Top20>Top10)且保低回撤;④排序 yield>复合>低PE(R2 全叠加误用低PE);
    # ⑤成长上限 8→10 加收益但越界稳定增长型;⑥regime 半仓降回撤但牺牲收益不划算。
    # 本轮全部用默认 yield 排序;#1(严守≤8%) vs #2(放宽≤10%)= 类型纯度对照实验。
    "3": [
        ("R3_y4_c300_t15", "股息≥4%+市值≥300+Top15(yield排序·核心全叠加·严守成长≤8%)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15}),
        ("R3_y4_c300_t15_cap10", "上者+成长上限放宽≤10%(类型边界·放宽组对照)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "np_cagr_max": 0.10}),
        ("R3_y4_t15", "股息≥4%+Top15 不加市值(纯型内低回撤对照:市值值不值那5pp回撤)",
         {"min_div_yield": 0.04, "top_n": 15}),
        ("R3_y4_c300_t12", "股息≥4%+市值≥300+Top12(更集中)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 12}),
        ("R3_y4_c300_t18", "股息≥4%+市值≥300+Top18(略分散)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 18}),
        ("R3_y4_c250_t15", "市值≥250亿(300与200之间)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 250.0, "top_n": 15}),
        ("R3_y4_c500_t15", "市值≥500亿(超大盘)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 500.0, "top_n": 15}),
        ("R3_y35_c300_t15", "股息≥3.5%(4%附近略放宽)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 15}),
        ("R3_y45_c300_t15", "股息≥4.5%(4%附近略收紧)",
         {"min_div_yield": 0.045, "mktcap_min_yi": 300.0, "top_n": 15}),
        ("R3_y4_c300_t15_g3", "加净利CAGR下限3%(剔近停滞)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "np_cagr_min": 0.03}),
        ("R3_y4_c300_t15_g5", "加净利CAGR下限5%(要求更实在增长)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "np_cagr_min": 0.05}),
        ("R3_y4_c300_t15_sec3", "每行业≤3只(高股息易堆银行/公用,分散)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 3}),
        ("R3_y4_c300_t15_sec2", "每行业≤2只(强分散)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2}),
        ("R3_y4_c300_t15_pe30", "PE上限放宽至30(高股息集内放宽估值)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "pe_max": 30.0}),
        ("R3_y4_c300_t15_rg07", "熊市0.7仓(轻择时降回撤,R2半仓太重)",
         {"min_div_yield": 0.04, "mktcap_min_yi": 300.0, "top_n": 15, "risk_off_exposure": 0.7}),
    ],
    # Round 4: 三强叠加 + 甜点继续下探。R3 三大可叠加正面杠杆(均未同时叠加):
    # ①股息门槛降3.5%(+1.88pp,且降回撤升Sharpe,推翻"4%甜点"——叠大盘+集中后高门槛=吃价值陷阱);
    # ②行业≤2只分散(+1.36pp,回撤不变,单调有效);③成长≤10%(+1.04pp但越界稳定增长型)。
    # 主线严守成长≤8%(默认),靠①②即可冲~11%,无需破纯度;仅留 #2 cap10 四叠加做对照。
    # 负面已坐实:成长下限/高门槛y4.5/cap250 全劣;PE非约束;择时不划算。
    "4": [
        # 三强叠加核心(严守成长≤8%)
        ("R4_y35_c300_t15_s2", "三强叠加:股息≥3.5%+市值≥300+Top15+行业≤2只(严守≤8%·核心)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2}),
        # 类型纯度对照:三强 + 放宽成长≤10%
        ("R4_y35_c300_t15_s2_cap10", "三强 + 成长放宽≤10%(类型纯度对照,看破纯度还值不值)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2, "np_cagr_max": 0.10}),
        # 股息门槛继续下探(配三强)
        ("R4_y30_c300_t15_s2", "股息≥3.0%(继续下探)+三强",
         {"min_div_yield": 0.030, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2}),
        ("R4_y325_c300_t15_s2", "股息≥3.25%+三强",
         {"min_div_yield": 0.0325, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2}),
        ("R4_y25_c300_t15_s2", "股息≥2.5%(探底)+三强",
         {"min_div_yield": 0.025, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2}),
        ("R4_y40_c300_t15_s2", "股息≥4.0%+三强(确认分散下3.5确优于4.0)",
         {"min_div_yield": 0.040, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2}),
        # 行业分散推到极限
        ("R4_y35_c300_t15_s1", "行业≤1只(极限分散)+y3.5",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 1}),
        # Top N 在分散框架下重扫
        ("R4_y35_c300_t12_s2", "Top12+三强(分散下收紧集中)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        ("R4_y35_c300_t20_s2", "Top20+三强(分散下放宽持仓)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 20, "max_per_sector": 2}),
        ("R4_y35_c300_t25_s2", "Top25+三强(更分散是否需更多持仓)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 25, "max_per_sector": 2}),
        # 市值门槛配 y3.5 重看
        ("R4_y35_c250_t15_s2", "市值≥250+y3.5+三强(低门槛下市值能否放松)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 250.0, "top_n": 15, "max_per_sector": 2}),
        ("R4_y35_c500_t15_s2", "市值≥500+y3.5+三强(超大盘+分散能否控回撤)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 500.0, "top_n": 15, "max_per_sector": 2}),
        # 双下探:门槛3.0 + 行业≤1
        ("R4_y30_c300_t15_s1", "股息≥3.0%+行业≤1只(双下探)",
         {"min_div_yield": 0.030, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 1}),
        # 排序键在新最优组合下重验
        ("R4_y35_c300_t15_s2_comp", "三强 + 复合排序(新组合下重验排序键)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2, "sort_by": "composite"}),
        # 三强 + 轻择时(压回撤试探)
        ("R4_y35_c300_t15_s2_rg07", "三强 + 熊市0.7仓(压回撤又尽量保收益)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 15, "max_per_sector": 2, "risk_off_exposure": 0.7}),
    ],
    # ── Round 5:鲁棒性/过拟合检验 —— 绕 3.5% 尖峰精扫 + Top 精扫 + 调仓重验,锁定最终版 ──
    "5": [
        # 股息门槛精扫(固定 c300+Top12+行业≤2):验证 3.5% 是平滑峰而非过拟合尖刺
        ("R5_y340_t12_s2", "股息≥3.40%(峰左0.1)",
         {"min_div_yield": 0.0340, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        ("R5_y345_t12_s2", "股息≥3.45%(峰左0.05)",
         {"min_div_yield": 0.0345, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        ("R5_y350_t12_s2", "股息≥3.50%(峰·复现锚 应=11.79)",
         {"min_div_yield": 0.0350, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        ("R5_y355_t12_s2", "股息≥3.55%(峰右0.05)",
         {"min_div_yield": 0.0355, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        ("R5_y360_t12_s2", "股息≥3.60%(峰右0.1)",
         {"min_div_yield": 0.0360, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        ("R5_y375_t12_s2", "股息≥3.75%(峰右0.25 过渡到4.0)",
         {"min_div_yield": 0.0375, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
        # Top 精扫(固定 y3.5+c300+行业≤2):确认 Top12 平台两侧平滑
        ("R5_y35_t10_s2", "Top10(峰左)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 10, "max_per_sector": 2}),
        ("R5_y35_t11_s2", "Top11(峰左)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 11, "max_per_sector": 2}),
        ("R5_y35_t13_s2", "Top13(峰右)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 13, "max_per_sector": 2}),
        ("R5_y35_t14_s2", "Top14(峰右)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 14, "max_per_sector": 2}),
        # 调仓频率在最优组合下重验(确认月度优势在三强画像下仍成立)
        ("R5_y35_t12_s2_q", "最优画像+季度调仓(低换手验证)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [3, 6, 9, 12]}),
        ("R5_y35_t12_s2_a", "最优画像+年度调仓(仅5月)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [5]}),
    ],
    # ── Round 6:年度调仓时点鲁棒性 —— 验证 13.31%@5月 是普遍优势还是时点过拟合 ──
    # 固定最优画像 y3.5+c300+Top12+行业≤2,只变调仓月份;看曲线平滑度与 5 月是否独优
    "6": [
        ("R6_a_m01", "年度调仓·1月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [1]}),
        ("R6_a_m02", "年度调仓·2月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [2]}),
        ("R6_a_m03", "年度调仓·3月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [3]}),
        ("R6_a_m04", "年度调仓·4月(年报披露前夜)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [4]}),
        ("R6_a_m05", "年度调仓·5月(复现锚 应=13.31)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [5]}),
        ("R6_a_m06", "年度调仓·6月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [6]}),
        ("R6_a_m07", "年度调仓·7月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [7]}),
        ("R6_a_m08", "年度调仓·8月(中报披露后)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [8]}),
        ("R6_a_m09", "年度调仓·9月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [9]}),
        ("R6_a_m10", "年度调仓·10月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [10]}),
        ("R6_a_m11", "年度调仓·11月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [11]}),
        ("R6_a_m12", "年度调仓·12月(年末)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [12]}),
        # 半年度对照(5+11月):介于年度与季度之间是否折中更优
        ("R6_h_0511", "半年度调仓·5+11月",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [5, 11]}),
        # 真峰 y3.45 叠加年度5月:能否把 13.31% 再推高、逼近 15%
        ("R6_a_m05_y345", "年度5月 + 股息真峰3.45%",
         {"min_div_yield": 0.0345, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2, "rebalance_months": [5]}),
    ],
    # ── Round 7:top_n<10 补扫 —— R5 只扫到 Top10(峰在12,左侧10→11→12 单调升),
    # 未验证更集中(5-9)的表现。固定最优画像(y3.5%+市值≥300+行业≤2,月度,同 R5 top 精扫口径),
    # 只变 top_n。t12 为复现锚(应=11.79%,校验与 R5 同口径)。更小 top_n 会抬高单票权重,
    # 尤其早年合格池仅 5-7 只时高度集中,重点看回撤/Sharpe 是否恶化。
    "7": [
        ("R7_t05_s2", "Top5(极集中)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 5, "max_per_sector": 2}),
        ("R7_t06_s2", "Top6",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 6, "max_per_sector": 2}),
        ("R7_t07_s2", "Top7",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 7, "max_per_sector": 2}),
        ("R7_t08_s2", "Top8",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 8, "max_per_sector": 2}),
        ("R7_t09_s2", "Top9",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 9, "max_per_sector": 2}),
        ("R7_t12_s2", "Top12(复现锚·应=11.79%)",
         {"min_div_yield": 0.035, "mktcap_min_yi": 300.0, "top_n": 12, "max_per_sector": 2}),
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
    strat = LynchSlowGrowersStrategy(param_overrides=overrides)
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
    out_json = OUT_DIR / f"lynch_sg_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# 林奇·缓慢增长型 参数探索 Round {round_tag}",
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
    (OUT_DIR / f"lynch_sg_r{round_tag}_overview.md").write_text("\n".join(lines))


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
    log.info("<<< DONE round %s -> exported/lynch_sg_r%s_overview.md",
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
