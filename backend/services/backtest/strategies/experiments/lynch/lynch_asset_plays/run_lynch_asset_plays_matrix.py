"""林奇·隐蔽资产型(Asset Plays)A 股策略参数探索 —— 诚实基线优先,目标平均年化 ≈15%。

加载 A 股 bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜(含沪深300基准)。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

隐蔽资产型 = 破净锚(pbMRQ<1.5)+ 有形账面折价(市值/(归母权益−商誉−无形)≤1.0,剔虚灵魂)
+ 归母净利>0 质量底线(防僵尸)+ 可选净现金增强 → Top N 等权月度调仓。买资产的市场折价,
等价值重估/释放。真「隐蔽资产」(土地/资源/品牌重估)无法机械提取,只能用代理指标逼近,天花板受限。

🚨 幸存者偏差(务必打折扣):破净股集中于银行/地产/钢铁/建筑;其中地产 2021+ 违约退市率高,
   缺失的「死亡样本」使回测偏乐观;破净又与「低估值风格周期」(2014底 / 2021-24 价值回归)绑定,
   结论须做子区间审计 + 幸存者偏差折扣,不追高年化而牺牲诚实性(参照周期型 6.43% 诚实基线的教训)。

用法:
  # rsmoke: 端到端验证 + 【样本量核验】(带决策日志, 看各调仓期够不够 Top20, 后台跑):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_asset_plays/run_lynch_asset_plays_matrix.py --round rsmoke \
      > logs/lynch_ap_rsmoke.log 2>&1 &
  # 全期跑 Round 1(后台):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_asset_plays/run_lynch_asset_plays_matrix.py --round 1 > logs/lynch_ap_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本随策略迁入 experiments/lynch/lynch_asset_plays/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_ap")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import balance_long, growth_long
from services.backtest.strategies.utils import st_filter
from services.backtest.strategies.experiments.lynch.lynch_asset_plays.asset_plays_strategy import (
    LynchAssetPlaysStrategy,
)

START = "2010-01-01"
END = "2026-06-01"

# 自闭环:回测产物(json/overview.md)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
# 策略默认(诚实基线): pb≤1.5(破净锚), tangible_pb≤1.0(有形折价, 剔商誉/无形),
#   require_positive_tbv=True, require_positive_np=True(归母净利>0 防僵尸), 净现金/负债/ROE 全关,
#   mktcap≥50亿, top20, tangible_pb升序(剔虚最便宜优先), 月度调仓, 无止损/择时.
ROUNDS: dict[str, list] = {
    # rsmoke: 单配置端到端验证 + 【样本量核验】(带决策日志, 看各调仓期 stage 通过数够不够 Top20)。
    #   全期跑, 用 flow.jsonl 里 strategy.pb_mktcap_liquidity / strategy.tangible_quality 的 passed
    #   计数判断: 早期年份(2010-2013)破净有形折价股是否稀少到填不满 top20 → 决定 R1 是否放宽阈值。
    "rsmoke": [
        ("AP_smoke", "默认诚实基线 smoke 验证 + 样本量核验", {}),
    ],
    # Round 1: 诚实基线 + 粗扫隐蔽资产型各主轴。
    #   (调仓频率 / 排序键 / 破净锚松紧 / 有形折价松紧 / 净现金增强 / 质量门槛 / 集中度 / 行业分散 /
    #    市值带 / 止损 / 择时)。目标先看朴素基线水平, 再看哪些正交杠杆有增益。
    "1": [
        ("R1_base", "诚实基线(pb≤1.5 有形pb≤1 净利>0 top20 月度 有形pb升序 mktcap≥50)", {}),
        # —— 调仓频率(价值型月度易 churn, 低频省换手且更贴 A 股年报节奏)——
        ("R1_quarter", "季度调仓", {"rebalance_months": [3, 6, 9, 12]}),
        ("R1_semiann", "半年调仓(6/12月)", {"rebalance_months": [6, 12]}),
        ("R1_annual_jun", "年度调仓(仅6月, 年报已披露)", {"rebalance_months": [6]}),
        # —— 排序键(默认有形pb升序=剔虚最便宜优先)——
        ("R1_sort_pb", "按普通PB升序", {"sort_by": "pb"}),
        ("R1_sort_netcash", "按净现金率降序(钱袋子优先)", {"sort_by": "net_cash"}),
        ("R1_sort_comp", "composite(有形PB低+净现金高)", {"sort_by": "composite"}),
        # —— 破净锚 PB 松紧 ——
        ("R1_pb10", "PB≤1.0(严格破净)", {"pb_max": 1.0}),
        ("R1_pb20", "PB≤2.0(放宽账面折价)", {"pb_max": 2.0}),
        ("R1_pb_off", "不卡普通PB(仅靠有形PB)", {"pb_max": 0.0}),
        # —— 有形折价松紧(灵魂锚)——
        ("R1_tpb08", "有形PB≤0.8(更深折价)", {"tangible_pb_max": 0.8}),
        ("R1_tpb12", "有形PB≤1.2(放宽)", {"tangible_pb_max": 1.2}),
        ("R1_tpb_off", "不卡有形PB(仅普通PB破净)", {"tangible_pb_max": 0.0}),
        # —— 净现金增强(格雷厄姆钱袋子, 现金最不可造假)——
        ("R1_netcash20", "净现金≥2成市值", {"min_net_cash_ratio": 0.20}),
        ("R1_netcash30", "净现金≥3成市值(强钱袋子)", {"min_net_cash_ratio": 0.30}),
        # —— 质量门槛 ——
        ("R1_np_off", "不要求净利>0(纯账面折价, 看盈利底线贡献)", {"require_positive_np": False}),
        ("R1_roe5", "ROE≥5%(剔弱质破净)", {"roe_min": 5.0}),
        ("R1_debt60", "负债率≤60%(防高杠杆爆雷)", {"max_debt_ratio": 0.60}),
        # —— 集中度 ——
        ("R1_top10", "Top10集中", {"top_n": 10}),
        ("R1_top30", "Top30分散", {"top_n": 30}),
        # —— 行业分散(破净集中银行/地产/钢铁, 分散尤重要)——
        ("R1_sec2", "每行业≤2(强制分散)", {"require_industry": True, "max_per_sector": 2}),
        ("R1_sec3", "每行业≤3", {"require_industry": True, "max_per_sector": 3}),
        # —— 市值带 ——
        ("R1_cap100", "市值≥100亿(大盘破净, 抗退市)", {"mktcap_min_yi": 100.0}),
        ("R1_cap_50_300", "市值50~300亿(剔巨型银行, 破净龙头集中银行)",
         {"mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0}),
        # —— 回撤压制 ——
        ("R1_trail25", "25%移动止损", {"trailing_stop_pct": 0.25}),
        # —— 择时(破净价值股熊市同样深跌)——
        ("R1_regime30_200", "熊市降至3成仓(200日线)",
         {"risk_off_exposure": 0.3, "regime_ma_days": 200}),
    ],
    # Round 2: 收益内核 —— 组合 R1 里经济自洽的增益杠杆, 排除所有减益项。
    #   R1 结论: ①净现金门槛(格雷厄姆钱袋子)风险调整后最强, 但 nc20 仅151笔(组合稀疏/含现金)
    #            ②低换手最稳健(半年 7.58% > 年度 6.88% > 季度 > 月度), 笔数健康
    #            ③深度价值(PB≤1.0 / 按净现金排序 / tpb≤1.2 填仓)温和增益
    #   减益(全剔除, 不进 R2): 择时/移动止损/Top10集中/行业分散/去有形锚/去净利门槛。
    #   R2 目标: 交叉「净现金阶梯(0.10/0.15/0.20) × 调仓频率(半年/年度) × 深度价值键」,
    #            在【风险调整收益】与【组合充实度(避免 nc20 过稀疏的小样本脆弱)】之间找内核。
    "2": [
        # —— 硬净现金门槛 × 低换手(nc20 太稀疏, 阶梯下探 15/10 求充实)——
        ("R2_semi_nc20", "半年+净现金≥20%", {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.20}),
        ("R2_semi_nc15", "半年+净现金≥15%", {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.15}),
        ("R2_semi_nc10", "半年+净现金≥10%(求充实)", {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.10}),
        ("R2_ann_nc20", "年度+净现金≥20%", {"rebalance_months": [6], "min_net_cash_ratio": 0.20}),
        ("R2_ann_nc15", "年度+净现金≥15%", {"rebalance_months": [6], "min_net_cash_ratio": 0.15}),
        # —— 深度价值键 × 低换手(不设硬净现金floor, 看软倾斜是否更充实且同样好)——
        ("R2_semi_pb10", "半年+PB≤1.0", {"rebalance_months": [6, 12], "pb_max": 1.0}),
        ("R2_semi_sortnc", "半年+按净现金降序", {"rebalance_months": [6, 12], "sort_by": "net_cash"}),
        ("R2_ann_sortnc", "年度+按净现金降序", {"rebalance_months": [6], "sort_by": "net_cash"}),
        # —— 三重组合: 净现金floor + 深度价值 + 低换手 ——
        ("R2_semi_nc15_pb10", "半年+净现金≥15%+PB≤1.0",
         {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.15, "pb_max": 1.0}),
        ("R2_semi_nc15_sortnc", "半年+净现金≥15%+按净现金降序",
         {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.15, "sort_by": "net_cash"}),
        ("R2_ann_nc15_pb10", "年度+净现金≥15%+PB≤1.0",
         {"rebalance_months": [6], "min_net_cash_ratio": 0.15, "pb_max": 1.0}),
        # —— 净现金floor + 质量/填仓辅助 ——
        ("R2_semi_nc15_roe5", "半年+净现金≥15%+ROE≥5%",
         {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.15, "roe_min": 5.0}),
        ("R2_semi_nc15_tpb12", "半年+净现金≥15%+有形PB≤1.2(填仓)",
         {"rebalance_months": [6, 12], "min_net_cash_ratio": 0.15, "tangible_pb_max": 1.2}),
        # —— 深度价值双键(无硬floor, 充实基准对照)——
        ("R2_semi_pb10_sortnc", "半年+PB≤1.0+按净现金降序",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash"}),
    ],
    # Round 3: 市值带精修 —— 全部构建在 R2 冠军内核 K 之上。
    #   K = 半年调仓[6,12] + PB≤1.0(破净) + 按净现金降序(钱袋子软倾斜) = R2 冠军 11.16%。
    #   R1 线索: 深度破净股在 A 股扎堆大盘银行/地产/钢铁, cap_50_300(剔巨型银行)曾微增益。
    #   目标: 在内核上扫市值下限/带宽, 看剔巨型银行(300亿+封顶)或下探小盘(20/30亿)是否增益,
    #         同时警惕小盘退市/幸存者偏差(小盘越低越吃幸存者偏差红利, R5/champ 再证伪)。
    #   内核 K = {"rebalance_months":[6,12], "pb_max":1.0, "sort_by":"net_cash"}(下方每个配置内联)。
    "3": [
        ("R3_k_ref", "内核K参照(mktcap≥50亿)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash"}),
        # —— 下限下探(纳入更多中小盘破净, 注意退市/幸存者偏差)——
        ("R3_cap30", "mktcap≥30亿",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash", "mktcap_min_yi": 30.0}),
        ("R3_cap20", "mktcap≥20亿(深挖小盘, 幸存者偏差警惕)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash", "mktcap_min_yi": 20.0}),
        # —— 下限上抬(只要大盘破净, 抗退市)——
        ("R3_cap100", "mktcap≥100亿",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash", "mktcap_min_yi": 100.0}),
        ("R3_cap150", "mktcap≥150亿",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash", "mktcap_min_yi": 150.0}),
        # —— 带宽封顶(剔巨型银行, 破净龙头集中大行)——
        ("R3_cap_50_300", "50~300亿(剔巨型银行)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0}),
        ("R3_cap_50_500", "50~500亿",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 500.0}),
        ("R3_cap_50_1000", "50~1000亿",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 1000.0}),
        ("R3_cap_30_300", "30~300亿(中小盘破净带)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 30.0, "mktcap_max_yi": 300.0}),
        ("R3_cap_100_1000", "100~1000亿(中大盘破净带)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 100.0, "mktcap_max_yi": 1000.0}),
    ],
    # R4:在 R3 冠军内核 K2(半年+PB≤1.0+净现金降序+50~300亿, 12.11%)上探集中度与收益 overlay。
    # 注意:R1 已证大盘择时/移动止损重伤本策略, 故 R4 不碰择时/止损, 改探
    #   ① 持仓数 top_n(集中度↔分散, 影响回撤)
    #   ② 个股趋势滤网 trend_ma_days(仅买价在自身均线上方者, 避"下落的刀"/价值陷阱, 收益增强)
    #   ③ 更深破净 pb_max 0.8 + 带宽微调(收益增强)
    "4": [
        ("R4_ref", "冠军内核K2参照(50~300亿)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0}),
        # —— 集中度 top_n(默认20) ——
        ("R4_top15", "top15(更集中)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "top_n": 15}),
        ("R4_top25", "top25(更分散)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "top_n": 25}),
        ("R4_top30", "top30(更分散, 抑回撤)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "top_n": 30}),
        # —— 个股趋势滤网(避价值陷阱/下落的刀, 收益增强)——
        ("R4_trend200", "+个股价>200日线",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 200}),
        ("R4_trend120", "+个股价>120日线",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 120}),
        ("R4_trend200_top30", "个股价>200日线 + top30(趋势+分散)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 200, "top_n": 30}),
        # —— 更深破净 + 带宽微调(收益增强)——
        ("R4_pb08", "pb_max 0.8(更深破净)",
         {"rebalance_months": [6, 12], "pb_max": 0.8, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0}),
        ("R4_cap_80_300", "80~300亿(剔最小盘)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 80.0, "mktcap_max_yi": 300.0}),
        ("R4_cap_50_500_top30", "50~500亿 + top30(软封顶+分散, 平衡回撤)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 500.0, "top_n": 30}),
    ],
    # R5:R4 证个股趋势滤网(价>自身均线)是最强杠杆(收益↑回撤↓双赢), trend120 冠军 13.99%。
    # 本轮 ① 精扫趋势均线周期找甜点(60/90/100/150/250) ② 对冠军 K3 做稳健性微扰
    #   (调仓频率/带宽/PB/top_n), 验证 13.99% 是否依赖单点参数、能否冲 15%。
    # 冠军内核 K3 = 半年[6,12] + PB≤1.0 + 净现金降序 + 50~300亿 + trend_ma 120。
    "5": [
        ("R5_ref", "冠军内核K3参照(trend120)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 120}),
        # —— 趋势均线周期精扫(找甜点)——
        ("R5_trend60", "趋势60日线(更快)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 60}),
        ("R5_trend90", "趋势90日线",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 90}),
        ("R5_trend100", "趋势100日线",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 100}),
        ("R5_trend150", "趋势150日线",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150}),
        ("R5_trend250", "趋势250日线(约1年)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 250}),
        # —— 冠军 K3 稳健性微扰(验证不依赖单点参数)——
        ("R5_trend120_ann", "trend120 + 仅年度调仓[6](频率微扰)",
         {"rebalance_months": [6], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 120}),
        ("R5_trend120_cap1000", "trend120 + 50~1000亿(带宽微扰:滤网后放宽封顶)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 1000.0, "trend_ma_days": 120}),
        ("R5_trend120_pb09", "trend120 + PB≤0.9(温和加深, pb08已证过深)",
         {"rebalance_months": [6, 12], "pb_max": 0.9, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 120}),
        ("R5_trend120_top25", "trend120 + top25(滤网后再测分散)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 120, "top_n": 25}),
    ],
    # champ:冠军内核 K4(R5 定, trend150, 全期 14.73%)的子区间时间稳健性审计。
    # 用 --start/--end/--label 分段跑(p1 2010-2015 早期机会稀缺 / p2 2016-2020 / p3 2021-2026 /
    # 2016+ 机会集充实后子期), 验证 14.73% 非依赖单一行情段, 并给出可发布的诚实年化。
    # 同时带 K3(trend120)与 top25 变体交叉验证子区间结论一致性。
    "champ": [
        ("CHAMP_trend150", "冠军K4(50~300亿+价>150日线)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150}),
        ("CHAMP_trend120", "K3对照(价>120日线)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 120}),
        ("CHAMP_trend150_top25", "K4+top25(风险精修变体)",
         {"rebalance_months": [6, 12], "pb_max": 1.0, "sort_by": "net_cash",
          "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0, "trend_ma_days": 150, "top_n": 25}),
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


def _run_one(sliced, tag, note, overrides, log_dir=None):
    strat = LynchAssetPlaysStrategy(param_overrides=overrides)
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
        log_dir=log_dir,
        enable_decision_log=log_dir is not None,
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
    out_json = OUT_DIR / f"lynch_ap_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# 林奇·隐蔽资产型 参数探索 Round {round_tag}",
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
    (OUT_DIR / f"lynch_ap_r{round_tag}_overview.md").write_text("\n".join(lines))


def _run_round(sliced, round_key, round_label, bench_annual, bench_total):
    """跑单轮所有 config(复用已切片的 bundle),增量写排行榜。

    rsmoke 轮为每个 config 开决策日志(log_dir=OUT_DIR/<tag>_log),
    便于事后 grep flow.jsonl 里 strategy.* 的 passed 计数核验样本量。
    """
    configs = ROUNDS[round_key]
    summaries = []
    log.info(">>> Round %s: %d configs", round_key, len(configs))
    for tag, note, ov in configs:
        log_dir = OUT_DIR / f"{tag}_log" if round_key == "rsmoke" else None
        try:
            summaries.append(_run_one(sliced, tag, note, ov, log_dir=log_dir))
        except Exception as e:
            log.exception("[%s] FAILED: %s", tag, e)
            summaries.append({"tag": tag, "note": note, "error": str(e)})
        _write(summaries, round_label, bench_annual, bench_total)
    log.info("<<< DONE round %s -> lynch_ap_r%s_overview.md", round_key, round_label)


def main():
    global START, END
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="rsmoke",
                    help="轮次号 (rsmoke | 1 | all)")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--label", default="", help="输出文件后缀(区分子区间跑)")
    args = ap.parse_args()

    if args.round == "all":
        round_keys = [k for k in ROUNDS.keys() if k != "rsmoke"]
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
