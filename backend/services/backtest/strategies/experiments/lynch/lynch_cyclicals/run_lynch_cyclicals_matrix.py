"""林奇·周期型(Cyclicals)A 股策略参数探索 —— 找平均年化 ≈15%。

加载 A 股 bundle 一次,对一组参数配置逐个跑完整回测,增量写排行榜(含沪深300基准)。
配置列表由 ROUNDS 字典按轮次组织;命令行传 --round 选择本次跑哪一轮。

周期型 = 周期行业白名单(钢/煤/有色/化工/建材/造纸/油/航运/工程机械/地产 + 可选汽车/设备)+
低 PB 谷底估值锚(刻意不卡 PE,规避市盈率悖论)+ 盈利从底部回升信号。择时而非选股:
谷底买、顶部前卖。与"快速增长型(小盘高增)""缓慢增长型(高股息)""稳健型(中速蓝筹)"互补。

🚨 周期股幸存者偏差远重于其它型(地产 2021+ / 部分钢铁煤炭真实违约退市),结论须打折扣。

用法:
  # 先 smoke 验证端到端(选 2015-2018 供给侧改革钢煤大复苏窗口, 后台跑):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_cyclicals/run_lynch_cyclicals_matrix.py --round smoke --start 2015-01-01 --end 2018-01-01 \
      > logs/lynch_cy_smoke.log 2>&1 &
  # 全期跑 Round 1(后台):
  nohup python backend/services/backtest/strategies/experiments/lynch/lynch_cyclicals/run_lynch_cyclicals_matrix.py --round 1 > logs/lynch_cy_r1.log 2>&1 &
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 本脚本随策略迁入 experiments/lynch/lynch_cyclicals/,上溯 7 层到项目根
ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lynch_cy")

from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.strategies.utils import growth_long
from services.backtest.strategies.utils import st_filter
from services.backtest.strategies.experiments.lynch.lynch_cyclicals.lynch_cyclicals_strategy import (
    LynchCyclicalsStrategy,
)

START = "2010-01-01"
END = "2026-06-01"

# 自闭环:回测产物(json/overview.md)直接落在本策略目录内
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- 各轮参数配置 ----------------
# 每个 config: (tag, note, param_overrides_dict)
# 策略默认: sector_tier=core, pb≤2.0, use_pe_filter=False(市盈率悖论), recovery=np_improve,
#           roe 全关, mktcap≥50亿, top20, pb升序(谷底优先), 月度调仓.
ROUNDS: dict[str, list] = {
    # smoke: 单配置, 仅验证端到端可跑通(配 2015-2018 供给侧改革钢煤复苏窗口前台/后台跑)
    "smoke": [
        ("CY_smoke", "默认配置 smoke 验证", {}),
    ],
    # Round 1: 粗扫周期型各主轴
    # (调仓频率 / 复苏信号 / 行业范围 / PB 松紧 / 排序 / 集中度 / 行业分散 / 止损 / 不追顶)
    "1": [
        ("R1_base", "基线(core pb≤2 np_improve top20 月度 pb排序 mktcap≥50)", {}),
        # —— 调仓频率(周期择时敏感: 更频繁 catch turn vs A股低频惯例)——
        ("R1_quarter", "季度调仓", {"rebalance_months": [3, 6, 9, 12]}),
        ("R1_semiann", "半年调仓(6/12月)", {"rebalance_months": [6, 12]}),
        ("R1_annual_jun", "年度调仓(仅6月, 年报已披露)", {"rebalance_months": [6]}),
        # —— 复苏信号(择时灵魂)——
        ("R1_rec_none", "无复苏信号(纯低PB深价值)", {"recovery_mode": "none"}),
        ("R1_rec_turn", "复苏=净利扭亏为盈(最强拐点)", {"recovery_mode": "np_turn"}),
        ("R1_rec_rev", "复苏=营收同比改善(更平滑)", {"recovery_mode": "rev_improve"}),
        ("R1_rec_roe", "复苏=ROE回升", {"recovery_mode": "roe_recover"}),
        # —— 行业范围 ——
        ("R1_core_noprop", "core去地产(规避地产幸存者偏差)", {"sector_tier": "core_no_prop"}),
        ("R1_broad", "broad(加汽车/航空/设备/橡塑/基建)", {"sector_tier": "broad"}),
        # —— PB 松紧(谷底估值锚)——
        ("R1_pb15", "PB≤1.5(更深谷底)", {"pb_max": 1.5}),
        ("R1_pb3", "PB≤3.0(放宽)", {"pb_max": 3.0}),
        ("R1_pb_off", "不卡PB(仅行业+复苏)", {"pb_max": 0.0}),
        # —— 排序 ——
        ("R1_sort_rec", "按复苏强度降序", {"sort_by": "recovery"}),
        ("R1_sort_comp", "composite(低PB+强复苏)", {"sort_by": "composite"}),
        # —— 集中度 ——
        ("R1_top10", "Top10集中", {"top_n": 10}),
        ("R1_top30", "Top30分散", {"top_n": 30}),
        # —— 行业分散(周期同涨同跌, 分散或降回撤)——
        ("R1_sec2", "每行业≤2(分散)", {"require_industry": True, "max_per_sector": 2}),
        # —— 回撤压制(周期股波动大, 移动止损尤为相关)——
        ("R1_trail25", "25%移动止损", {"trailing_stop_pct": 0.25}),
        # —— 不追顶(ROE 已处景气高位则不买)——
        ("R1_roemax15", "ROE≤15 不追周期顶", {"roe_max": 15.0}),
    ],
    # Round 2: R1 定论 —— 复苏信号(np_improve)是灵魂(去掉即亏 -0.65%);base 各维(core/pb≤2/top20/
    #   月度/pb升序)均为局部最优, 唯一击败 base 的杠杆 = 25%移动止损(6.43% 且 mdd 51→46, Sharpe 最高).
    #   残酷面: 全配置 mdd 46-63% / Sharpe≤0.27, 机械化周期型远不及 15%。
    # R2 锚点 = base + trail25。两大攻坚: ① 优化移动止损甜点; ② 用未测的「择时/趋势」杠杆狠压 46% 回撤
    #   (回撤是 Sharpe 与复利的最大杀手, 压回撤的边际收益远大于再榨收益), 辅以复苏阈值/不追顶/质量/市值。
    "2": [
        ("R2_anchor", "锚点: base + 25%移动止损(复跑校验≈6.43%)",
         {"trailing_stop_pct": 0.25}),
        # —— 移动止损甜点扫描(唯一已证赢家)——
        ("R2_trail15", "trail15%(很紧, 早锁利)", {"trailing_stop_pct": 0.15}),
        ("R2_trail20", "trail20%(紧)", {"trailing_stop_pct": 0.20}),
        ("R2_trail30", "trail30%(松)", {"trailing_stop_pct": 0.30}),
        ("R2_stop30", "30%硬止损(替代移动止损)", {"stop_loss_pct": 0.30}),
        # —— 沪深300 regime 择时(攻坚 46% 回撤, R2 最大看点)——
        ("R2_regime30_200", "trail25 + 熊市降至3成仓(200日线)",
         {"trailing_stop_pct": 0.25, "risk_off_exposure": 0.3, "regime_ma_days": 200}),
        ("R2_regime00_200", "trail25 + 熊市清仓(200日线)",
         {"trailing_stop_pct": 0.25, "risk_off_exposure": 0.0, "regime_ma_days": 200}),
        ("R2_regime30_125", "trail25 + 熊市3成仓(125日线, 更灵敏)",
         {"trailing_stop_pct": 0.25, "risk_off_exposure": 0.3, "regime_ma_days": 125}),
        # —— 个股趋势过滤(避免接落刀/价值陷阱)——
        ("R2_trend200", "trail25 + 个股站上200日线才买",
         {"trailing_stop_pct": 0.25, "trend_ma_days": 200}),
        ("R2_trend60", "trail25 + 个股站上60日线才买(短趋势)",
         {"trailing_stop_pct": 0.25, "trend_ma_days": 60}),
        # —— 复苏强度阈值(base 仅要求"改善>0", 收紧)——
        ("R2_recmin10", "trail25 + 复苏≥10%(更强拐点)",
         {"trailing_stop_pct": 0.25, "recovery_min_pct": 0.10}),
        ("R2_recmin20", "trail25 + 复苏≥20%(强拐点)",
         {"trailing_stop_pct": 0.25, "recovery_min_pct": 0.20}),
        # —— 不追顶(景气高位 ROE 不买)——
        ("R2_roemax15", "trail25 + ROE≤15 不追顶",
         {"trailing_stop_pct": 0.25, "roe_max": 15.0}),
        ("R2_roemax20", "trail25 + ROE≤20 不追顶",
         {"trailing_stop_pct": 0.25, "roe_max": 20.0}),
        # —— 质量底线(剔结构性衰退伪周期)——
        ("R2_debt60", "trail25 + 负债率≤60%",
         {"trailing_stop_pct": 0.25, "max_debt_ratio": 0.60}),
        ("R2_cfo05", "trail25 + 经营现金流/净利≥0.5",
         {"trailing_stop_pct": 0.25, "min_cfo_np_ratio": 0.5}),
        # —— 市值带(大盘周期更抗跌 vs 中小盘弹性, 慎幸存者偏差)——
        ("R2_cap100", "trail25 + 市值≥100亿",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 100.0}),
        ("R2_cap200", "trail25 + 市值≥200亿",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 200.0}),
        # —— 幸存者偏差诚实变体 ——
        ("R2_noprop", "trail25 + core去地产(诚实变体)",
         {"trailing_stop_pct": 0.25, "sector_tier": "core_no_prop"}),
    ],
    # Round 3: R2 定论 —— trail25=6.43% 仍是天花板, 移动止损甜点=25%(硬止损/更松更紧均更差);
    #   择时(regime)/个股趋势过滤全线崩(与"抄底=股价在均线下"根本冲突); 复苏幅度(recmin)完全无关
    #   (只看符号); 质量门槛(debt/cfo)、放大市值(cap100/200)全部伤害。单参数主轴已扫尽无增益。
    # R2 唯一露出信号的维度 = 市值: 50亿(6.43%) >> 100亿(3.96%) >> 200亿(-0.40%), 单调递减
    #   → 强烈暗示「周期复苏 alpha 集中在中小盘」。R3 锚点仍 = base + trail25, 三条主线:
    #   ① 反向验证: 加「市值上限」逼出纯小/中盘, 看是否击穿 6.43% 天花板(⚠️小盘幸存者偏差最重, 结论需打折);
    #   ② 未测正交单项: PB 下限(剔极低PB价值陷阱) / 流动性收紧(证伪小盘是否只是流动性幻觉) / top_n 细分(15/25);
    #   ③ 诚实/温和杠杆组合: 去地产 + 不追顶 + 更深谷底 的两两叠加。
    "3": [
        ("R3_anchor", "锚点: base + trail25(确定性复校≈6.43%)",
         {"trailing_stop_pct": 0.25}),
        # —— ① 市值上限: 逼出纯小/中盘, 验证 alpha 是否集中小盘(核心看点)——
        ("R3_cap_le80", "trail25 + 市值 50~80亿(纯小盘)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 80.0}),
        ("R3_cap_le100", "trail25 + 市值 50~100亿(小盘)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0}),
        ("R3_cap_le150", "trail25 + 市值 50~150亿(中小盘)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 150.0}),
        ("R3_cap_le300", "trail25 + 市值 50~300亿(剔超大盘钢煤油龙头)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 300.0}),
        # —— ② PB 下限: 剔除极低 PB(退市边缘/结构性价值陷阱)——
        ("R3_pbmin05", "trail25 + PB 0.5~2.0(剔极低PB陷阱)",
         {"trailing_stop_pct": 0.25, "pb_min": 0.5}),
        ("R3_pbmin08", "trail25 + PB 0.8~2.0(账面更健康)",
         {"trailing_stop_pct": 0.25, "pb_min": 0.8}),
        # —— ② 流动性收紧: 证伪「小盘弹性=流动性/微盘幻觉」——
        ("R3_amt3000", "trail25 + 日均成交≥3000万",
         {"trailing_stop_pct": 0.25, "min_amount_cny": 3e7}),
        ("R3_amt5000", "trail25 + 日均成交≥5000万",
         {"trailing_stop_pct": 0.25, "min_amount_cny": 5e7}),
        # —— ② 集中度细分(20 为 R1 甜点, 探两侧邻域)——
        ("R3_top15", "trail25 + Top15(更集中)",
         {"trailing_stop_pct": 0.25, "top_n": 15}),
        ("R3_top25", "trail25 + Top25(更分散)",
         {"trailing_stop_pct": 0.25, "top_n": 25}),
        # —— ③ 诚实/温和杠杆组合 ——
        ("R3_roemax15_noprop", "trail25 + ROE≤15不追顶 + 去地产(诚实组合)",
         {"trailing_stop_pct": 0.25, "roe_max": 15.0, "sector_tier": "core_no_prop"}),
        ("R3_pb15_roemax15", "trail25 + PB≤1.5更深谷底 + ROE≤15不追顶",
         {"trailing_stop_pct": 0.25, "pb_max": 1.5, "roe_max": 15.0}),
    ],
    # Round 4: R3 突破 —— 市值「带」是唯一击穿 6.43% 天花板的杠杆: 50~100亿=8.33%/Sharpe0.34(全研究最佳),
    #   倒 U 型两侧单调下滑(50~80=4.02 / 50~150=7.44 / 50~300=6.69 / base=6.43 / ≥100=3.96 / ≥200=-0.40)。
    #   大盘龙头稀释收益。副证: 流动性收紧单调伤害(≥3000万=4.78 / ≥5000万=3.29)→ 超额集中于低流动性小盘
    #   (⚠️实盘滑点+小盘幸存者偏差, 8.33% 大概率高估); PB≥0.5 微正(6.56), Top20 仍是峰值。
    # R4 锚点 = base + trail25 + 市值 50~100亿(8.33%, mdd 50.81%)。三条主线:
    #   ① 精修市值带(挪动上/下限, 找 Sharpe/回撤更优的中枢; 含右移中枢以减小最小盘的幸存者依赖);
    #   ② 攻回撤(冠军 mdd 50.81% > anchor 46.48%, 是最大短板): trail 收紧 / 行业分散 / 熊市降仓 在小盘带上重测;
    #   ③ 叠加温和正向 + 诚实变体(PB≥0.5 / ROE≤15 / 复苏≥10% / 去地产)看能否在 8.33% 上再进或更稳。
    "4": [
        ("R4_anchor", "锚点: base + trail25 + 市值50~100亿(确定性复校≈8.33%)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0}),
        # —— ① 精修市值带: 挪上/下限 + 右移中枢 ——
        ("R4_band_60_100", "市值 60~100亿(抬下限)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 60.0, "mktcap_max_yi": 100.0}),
        ("R4_band_40_100", "市值 40~100亿(降下限, ⚠️微盘幸存者偏差, 仅刻画)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 40.0, "mktcap_max_yi": 100.0}),
        ("R4_band_50_90", "市值 50~90亿(收窄上限)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 90.0}),
        ("R4_band_50_120", "市值 50~120亿(放宽上限)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 120.0}),
        ("R4_band_70_130", "市值 70~130亿(中枢右移, 减最小盘幸存者依赖)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 70.0, "mktcap_max_yi": 130.0}),
        # —— ② 攻回撤(冠军 mdd 50.81% 是最大短板)——
        ("R4_trail20", "冠军 + trail20(收紧止损压回撤)",
         {"trailing_stop_pct": 0.20, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0}),
        ("R4_trail30", "冠军 + trail30(放松止损, 对照)",
         {"trailing_stop_pct": 0.30, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0}),
        ("R4_sec2", "冠军 + 每行业≤2(分散压回撤)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "require_industry": True, "max_per_sector": 2}),
        ("R4_regime30_200", "冠军 + 熊市降至3成仓(小盘带上重测择时)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "risk_off_exposure": 0.3, "regime_ma_days": 200}),
        # —— ③ 叠加温和正向 + 诚实变体 ——
        ("R4_pbmin05", "冠军 + PB≥0.5(剔极低PB陷阱, R3微正)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "pb_min": 0.5}),
        ("R4_roemax15", "冠军 + ROE≤15不追顶",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "roe_max": 15.0}),
        ("R4_recmin10", "冠军 + 复苏≥10%(更强拐点)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "recovery_min_pct": 0.10}),
        ("R4_noprop", "冠军 + 去地产(诚实变体)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
    ],
    # Round 5: R4 再突破 —— 在 50~100亿小盘带上「去地产」= 10.38%/Sharpe0.41/mdd49.5%(全研究最佳)!
    #   机理: 2021 后小盘地产结构性崩塌(违约潮), 在集中 top20 里挤占更优周期股; 去掉即释放收益,
    #   且恰是幸存者偏差最轻的诚实变体(诚实变体反而最强, 可辩护)。另: trail 甜点因小盘高波动左移(20>25>30,
    #   trail20 单独=8.54%); 市值带峰值尖(各扰动皆降, 70~130亿=7.27% 为抗幸存者稳健带); 择时依旧败(5.30%)
    #   但把 mdd 压到 42.5%(全场最低, 仅宜防御)。
    # R5 = 收敛定稿。锚点 = base + 市值50~100亿 + 去地产 + trail25(10.38%)。三条主线:
    #   ① 叠加两大赢家: 去地产 × trail{15/18/20/22} 找联合最优(两者单独皆正, 期望联合更高);
    #   ② 稳健性备选: 去地产 × 更宽/右移市值带(50~150 / 70~130), 牺牲少许收益换抗过拟合/抗幸存者偏差;
    #   ③ 防御变体: 去地产 × 行业分散 / 熊市降仓(用较低收益换更低回撤, 服务风险厌恶者)。
    # 全期跑完后, 另起 R5champ 把最终冠军在 2010-16 / 2016-21 / 2021-26 三子区间复跑, 验证非单窗口过拟合。
    "5": [
        ("R5_anchor", "锚点: 市值50~100亿 + 去地产 + trail25(确定性复校≈10.38%)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
        # —— ① 叠加两大赢家: 去地产 × trail 甜点(小盘偏紧)——
        ("R5_trail22", "去地产带 + trail22",
         {"trailing_stop_pct": 0.22, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
        ("R5_trail20", "去地产带 + trail20(两赢家联合)",
         {"trailing_stop_pct": 0.20, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
        ("R5_trail18", "去地产带 + trail18(更紧)",
         {"trailing_stop_pct": 0.18, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
        ("R5_trail15", "去地产带 + trail15(测紧边界)",
         {"trailing_stop_pct": 0.15, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
        ("R5_pbmin05", "去地产带 + trail25 + PB≥0.5(增稳健)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop", "pb_min": 0.5}),
        # —— ② 稳健性备选: 更宽/右移市值带 × 去地产(抗过拟合/幸存者偏差)——
        ("R5_band_50_150_np", "去地产 + 市值50~150亿(更宽带, 抗过拟合)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 150.0,
          "sector_tier": "core_no_prop"}),
        ("R5_band_70_130_np", "去地产 + 市值70~130亿(中枢右移, 抗幸存者)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 70.0, "mktcap_max_yi": 130.0,
          "sector_tier": "core_no_prop"}),
        # —— ③ 防御变体: 去地产带 × 分散 / 熊市降仓(低收益换低回撤)——
        ("R5_sec2", "去地产带 + 每行业≤2(分散压回撤)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop", "require_industry": True, "max_per_sector": 2}),
        ("R5_regime30_200", "去地产带 + 熊市降至3成仓(防御, 压回撤)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop", "risk_off_exposure": 0.3, "regime_ma_days": 200}),
    ],
    # champ: 子区间稳健性检验(过拟合审计)。用 --label p1/p2/p3 + --start/--end 三段跑:
    #   p1 2010-01~2016-01(熊/震荡, CSI300≈0.9%)、p2 2016-01~2021-01(供给侧+商品牛, CSI300≈8.5%, 周期黄金期)、
    #   p3 2021-01~2026-06(CSI300≈-1.5%)。全样本优化 5 轮把年化从 6.2%→11.1%, 疑似渐进过拟合(市值带峰值尖锐 /
    #   去地产红利仅在 50-100 窄带出现不泛化 / 每轮 +1-2pp)。本轮把「全样本冠军」与「稳健基线」并排放三段,
    #   若冠军仅在 p2 大胜、p1/p3 崩 → 坐实过拟合(策略实为「周期股在 2016-21 走强」而非全天候 alpha)。
    "champ": [
        ("CH_sec2", "全样本冠军: 50~100亿+去地产+trail25+行业≤2(全期11.11%)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop", "require_industry": True, "max_per_sector": 2}),
        ("CH_anchor", "次冠军: 50~100亿+去地产+trail25(全期10.38%)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 100.0,
          "sector_tier": "core_no_prop"}),
        ("CH_band150", "稳健宽带: 50~150亿+trail25(含地产, 全期7.44%)",
         {"trailing_stop_pct": 0.25, "mktcap_min_yi": 50.0, "mktcap_max_yi": 150.0}),
        ("CH_base", "朴素基线: base+trail25(全域, 全期6.43%)",
         {"trailing_stop_pct": 0.25}),
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
    strat = LynchCyclicalsStrategy(param_overrides=overrides)
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
    out_json = OUT_DIR / f"lynch_cy_r{round_tag}.json"
    out_json.write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    ok = [s for s in summaries if "annualized_return" in s]
    ok.sort(key=lambda s: s["annualized_return"], reverse=True)
    lines = [
        f"# 林奇·周期型 参数探索 Round {round_tag}",
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
    (OUT_DIR / f"lynch_cy_r{round_tag}_overview.md").write_text("\n".join(lines))


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
    log.info("<<< DONE round %s -> exported/lynch_cy_r%s_overview.md",
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
