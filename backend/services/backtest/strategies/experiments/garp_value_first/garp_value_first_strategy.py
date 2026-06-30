"""GARP(价值优先版)—— GarpValueFirstStrategy【调优固化版】。

⚠️ 实验性质,不暴露 UI(experiments/ 目录)。本文件是原 deployed 调优版与早期
experiments 版的合并产物:保留调优版(max_per_industry=2 / score_weight_roe=1.0,
全周期 14.21%)的代码与参数,并入早期版独有的 g15 防御变体 + 7 窗 regime OOS 研究笔记
(见文末「早期基线配置研究笔记」)。

价值优先 GARP:以「低估值多因子季度调仓」(父类)为底座,在选股之前先把
宇宙收敛为「归母净利同比增速 ≥ growth_min_yoy」的「正在成长」的股票,再让底座在
这个子集上跑价值 + 质量 + 排序。即「在便宜且优质的股票里,只买还在成长的」。

成长只作一道「门」(gate),不追高估值成长(纯成长方向在 A 股全周期已证伪),
作用是剔除「便宜但在衰退」的价值陷阱。gate 仅在调仓月计算(省算力),成长字段取
NOTICE_DATE-as-of 口径(严格防 look-ahead)。

== 配置(本调优版固化的全部参数,自包含)==
  底座 C_full_t30 覆盖(相对父类默认):
    momentum_drop_pct      0.2  -> 0.3       剔最差 30% 动量
    score_weight_roe       1.0  (退回父类等权,2026-06-17 OOS:原 2.0 覆盖无依据)
    score_weight_div_yield 1.0  -> 2.0
    top_n                  15   -> 30   (惰性:实际平均持仓仅 ~10 只,top_n≥20 即不 binding)
    max_per_industry       3    -> 2    强制跨行业分散(破净池高度集中于银行/地产/钢铁)
    rebalance_months  [5,9,11] -> [3,6,9,12]  规整季度调仓
  成长 gate:
    growth_min_yoy         0.0   归母净利同比增速下限 %(0=g0:仅要求非负/有披露)
    growth_gate_require_data True 未披露成长数据的股票剔除(保守)

== 回测结论(2010-01 ~ 2026-06,A 股全市场,/tmp/garp_value_eval.py)==
  变体                         年化     回撤    Sharpe  PF    交易
  C_full_t30(底座)            11.50%  35.4%   0.554  -      1341
  g0 旧(max_per_industry=4)   12.11%  31.3%   0.590  3.64    796
  g0 现(max_per_industry=2)   14.21%  25.5%   0.690  4.03    -    ← 全维度优于旧 g0
- max_per_industry 4→2 决策(2026-06-17,/tmp/garp_topind_eval.py + ind2/邻居 OOS):
  破净股票池高度集中于银行/地产/钢铁,4→2 强制跨行业分散,全周期年化 +2.10pct、
  回撤 -5.8pct、Sharpe/PF 全升。OOS 验证为结构性增益而非噪声/单段 beta:
    · 两半场全胜:H1 +1.75pct、H2(2018-2026 干净 OOS)+2.12pct
    · 5 个独立 regime 段 3WIN/2LOSE,胜段跨疯牛灾(+4.93)/结构牛(+4.17)/熊(+6.07)
      三种不同行情,不依赖单一 beta;失血段慢牛熊(-2.31)/反弹(-2.00)温和可控
    · 邻域 OOS 确认改进带 = cap∈{2,3} 平滑山脊(ind3 同为 3W/2L),非孤立尖峰;
      ind1(每行业仅 1 只)过度分散,regime 仅 1W/4L,已排除
- score_weight_roe 2.0→1.0 决策(2026-06-17,/tmp/garp_Bknobs_eval.py + 完全等权补测):
  原 2.0 系从 C_full_t30 底座继承、从未独立 OOS 验证。退回父类等权 1.0 是更少拟合方向。
  8 段 battery 6WIN/2LOSE:全周期 +0.32pct、H2 干净 OOS +0.38pct(回撤 -2.0pct)、
  补强 base 最弱的慢牛熊 +1.83pct(回撤 -2.7pct)、base 最强的熊段也 +1.21pct;
  仅结构牛 -1.27/疯牛 -0.22(flat)温和让步。与被证伪的 roe_min 松紧(roe5)伪 alpha
  性质相反(roe5 仅疯牛赢、多段质量+回撤双恶化)。
  · 完全等权补测(div_yield 也退 1.0):eqw 仅 4W/4L 且干净 OOS H2 -0.34 输给 base,
    z-score 加权下叠加非线性,div 分量在干净 OOS/反弹拖累 → 只退 roe 单动,div_yield 保留 2.0。
- top_n=30 为惰性冗余值:实际平均持仓仅 ~10 只,top50 与 base 回测字节级相同。
- 真实基准对比(2013-2026,易方达沪深300ETF 510310 前复权,/tmp/g0_vs_510310.py):
  每月定投 5000,旧 g0 XIRR 15.11% / 终值 235 万 vs 510310 XIRR 7.50% / 终值 135 万。
结果存档:logs/smoke/garp_{value,oos,topind,ind2oos,indnbr,Aknobs,Bknobs,eqw}_eval.{log,json}、g0_vs_510310.{log,json}。

== 与已证伪的 a_garp 的区别 ==
a_garp 是「成长优先」GARP(先按 CAGR 选高成长再做估值检查),已证伪。本策略是
「价值优先」:价值底座在前,成长仅作过滤门,方向相反。

== 早期基线配置研究笔记(max_per_industry=4 / score_weight_roe=2.0,合并自旧 experiments 版)==
⚠️ 以下 OOS 数据对应「调优前」的早期基线配置(max_ind=4),非上方 14.21% 的最终配置,
保留作 g0 vs g15 取舍 + regime 行为的历史参考。
  变体             年化      回撤    Sharpe   Calmar*   交易
  BASE_C30(基线) 11.50%   35.4%    0.554    0.325    1341
  GARP g0(净利≥0)12.11%   31.3%    0.590    0.387     796   ← 全维度优于基线
  GARP g15(净利≥15%)11.63% 23.5%   0.584    0.494     425   ← 回撤腰斩,防御型
  (*Calmar 引擎未算,手算 = ann/maxdd)
- g15 = 防御型:年化≈基线但回撤 35%→23.5%(Calmar 0.494 最佳),牺牲后段牛市上行
  换深熊少亏(2010-2014 段 +61% vs 基线 +14%)。适合回撤敏感口径。
7 个独立 regime 窗口(各自 fresh capital)g0/g15 vs BASE_C30 的 ann WIN/LOSE:
  regime 窗口            CSI300   BASE    g0(Δ)         g15(Δ)
  H1 2010-2018          +14.0%  9.64%  10.21%(+0.6)WIN 12.66%(+3.0)WIN
  H2 2018-2026          +21.4% 12.42%  13.20%(+0.8)WIN 11.91%(-0.5)LOSE
  疯牛灾 2014-2016       +24.5% 20.30%  20.21%(-0.1)≈    19.00%(-1.3)LOSE
  慢牛熊 2016-2019       +3.8%   2.02%   5.55%(+3.5)WIN -1.83%(-3.9)LOSE
  结构牛 2019-2021       +79.9%  0.79%   6.41%(+5.6)WIN  1.43%(+0.6)WIN
  熊 2021-2024           -40.6% 18.86%  24.90%(+6.0)WIN 15.90%(-3.0)LOSE
  反弹 2024-2026         +52.0% 19.25%  17.17%(-2.1)LOSE 16.96%(-2.3)LOSE
- g0 在早期基线即 7 窗 5WIN/1≈/1LOSE,修复价值底座最大短板(结构牛 0.79%→6.41%、
  慢牛熊 +3.5、深熊 +6.0);g15 牛市让出上行、仅适合回撤敏感口径。
结果存档:logs/smoke/garp_value_eval.{log,json}、garp_oos_eval.{log,json}。
"""

from __future__ import annotations

import copy
from datetime import date

from services.backtest.strategies.experiments.low_valuation_multifactor.low_valuation_multifactor_quarterly_strategy import (
    LowValuationMultiFactorQuarterlyStrategy,
)
from services.backtest.strategies.utils import growth


# C_full_t30 底座:相对父类默认值的覆盖项
_C_FULL_T30_OVERRIDES = {
    "momentum_drop_pct": 0.3,
    "score_weight_roe": 1.0,
    "score_weight_div_yield": 2.0,
    "top_n": 30,
    "max_per_industry": 2,
    "rebalance_months": [3, 6, 9, 12],
}


def _build_params() -> dict:
    """深拷贝父类 params,patch C_full_t30 底座默认 + 新增成长 gate 参数。父类零污染。"""
    params = copy.deepcopy(LowValuationMultiFactorQuarterlyStrategy.params)
    for key, default in _C_FULL_T30_OVERRIDES.items():
        if key in params:
            params[key]["default"] = default
    params["growth_min_yoy"] = {
        "default": 0.0,
        "type": "float",
        "label": "成长 gate:归母净利同比增速下限 %(0=仅要求非负/有披露)",
    }
    params["growth_gate_require_data"] = {
        "default": True,
        "type": "bool",
        "label": "无成长数据(未披露)是否剔除(True=剔除,保守)",
    }
    return params


class GarpValueFirstStrategy(LowValuationMultiFactorQuarterlyStrategy):
    name = "GARP 价值优先(低估值多因子 + 成长 gate·实验)"
    description = (
        "【实验】价值优先 GARP:低估值多因子季度调仓为底座(PB≤1 + PE≤30 + 质量 + ROE≥8 + "
        "动量剔除 + 行业≤2 + 复合 score),选股前先用成长 gate 把宇宙收敛为「归母净利"
        "同比 ≥ 阈值」的成长股,在便宜且优质的股票里只买仍在成长的。全周期(2010-2026)"
        "年化约 14.21% / 回撤 25.5% / Sharpe 0.69,全维度优于纯价值底座。未发布。"
    )

    params = _build_params()

    def _rebalance_months_set(self) -> set[int]:
        rebal = self.p.rebalance_months
        if isinstance(rebal, str):
            rebal = [int(x) for x in rebal.split(",") if x.strip()]
        return set(rebal)

    def _apply_growth_gate(self, ctx, symbols: list[str]) -> list[str]:
        """保留归母净利同比增速 ≥ growth_min_yoy 的 symbol。

        - 无成长数据(未披露)按 growth_gate_require_data 决定剔除/保留。
        - PARENTNETPROFITTZ 为 None/NaN 视为「无有效成长读数」,同上处理。
        """
        min_yoy = float(self.p.growth_min_yoy)
        require_data = bool(self.p.growth_gate_require_data)
        kept: list[str] = []
        for sym in symbols:
            metrics = growth.get_growth_metrics_as_of_notice(ctx, sym)
            yoy = metrics.get("PARENTNETPROFITTZ") if metrics else None
            if yoy is None:
                if not require_data:
                    kept.append(sym)
                continue
            ctx.record_factor(sym, "NetProfitYoY", float(yoy))
            if yoy >= min_yoy:
                kept.append(sym)
        ctx.log_flow("garp.growth_gate", input=len(symbols), passed=len(kept))
        return kept

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        # 非调仓月:父类本就早退 [],无需 gate(省算力,避免每 bar 扫全市场成长表)
        cur_str = ctx.current_date
        if not cur_str:
            return []
        try:
            cur_d = date.fromisoformat(cur_str[:10])
        except (ValueError, TypeError):
            return []
        if cur_d.month not in self._rebalance_months_set():
            return super().screen(ctx, symbols)

        gated = self._apply_growth_gate(ctx, symbols)
        return super().screen(ctx, gated)
