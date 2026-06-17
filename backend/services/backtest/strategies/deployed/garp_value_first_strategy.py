"""GARP(价值优先版)—— GarpValueFirstStrategy【已发布 / 最终交付】。

价值优先 GARP:以「低估值多因子季度调仓」(deployed 父类)为底座,在选股之前先把
宇宙收敛为「归母净利同比增速 ≥ growth_min_yoy」的「正在成长」的股票,再让底座在
这个子集上跑价值 + 质量 + 排序。即「在便宜且优质的股票里,只买还在成长的」。

成长只作一道「门」(gate),不追高估值成长(纯成长方向在 A 股全周期已证伪),
作用是剔除「便宜但在衰退」的价值陷阱。gate 仅在调仓月计算(省算力),成长字段取
NOTICE_DATE-as-of 口径(严格防 look-ahead)。

== 配置(本交付版固化的全部参数,自包含,不依赖 experiments)==
  底座 C_full_t30 覆盖(相对 deployed 父类默认):
    momentum_drop_pct      0.2  -> 0.3       剔最差 30% 动量
    score_weight_roe       1.0  -> 2.0
    score_weight_div_yield 1.0  -> 2.0
    top_n                  15   -> 30
    max_per_industry       3    -> 4
    rebalance_months  [5,9,11] -> [3,6,9,12]  规整季度调仓
  成长 gate:
    growth_min_yoy         0.0   归母净利同比增速下限 %(0=g0:仅要求非负/有披露)
    growth_gate_require_data True 未披露成长数据的股票剔除(保守)

== 回测结论(2010-01 ~ 2026-06,A 股全市场,/tmp/garp_value_eval.py)==
  变体              年化     回撤    Sharpe  Calmar  交易
  C_full_t30(底座) 11.50%  35.4%   0.554   0.325   1341
  本策略 g0(净利≥0)12.11%  31.3%   0.590   0.387    796   ← 全维度优于底座
- g0 相对底座:年化↑、回撤↓、Sharpe↑、换手↓,几乎「免费」的改进。
- OOS 7 个独立 regime 窗口(各 fresh capital,/tmp/garp_oos_eval.py):5 WIN / 1≈ / 1 LOSE,
  每窗口均跑赢 CSI300;修复了价值底座最大短板(结构牛 2019-2021:底座 0.79% → g0 6.41%)。
  唯一弱点 = 2024-2026 近端反弹略逊底座(-2.1pct)。
- 真实基准对比(2013-2026,易方达沪深300ETF 510310 前复权,/tmp/g0_vs_510310.py):
  每月定投 5000,g0 XIRR 15.11% / 终值 235 万 vs 510310 XIRR 7.50% / 终值 135 万。
结果存档:logs/smoke/garp_{value,oos}_eval.{log,json}、g0_vs_510310.{log,json}。

== 与已证伪的 a_garp 的区别 ==
a_garp 是「成长优先」GARP(先按 CAGR 选高成长再做估值检查),已证伪。本策略是
「价值优先」:价值底座在前,成长仅作过滤门,方向相反。
"""

from __future__ import annotations

import copy
from datetime import date

from services.backtest.strategies.deployed.low_valuation_multifactor_quarterly_strategy import (
    LowValuationMultiFactorQuarterlyStrategy,
)
from services.backtest.strategies.utils import growth


# C_full_t30 底座:相对 deployed 父类默认值的覆盖项
_C_FULL_T30_OVERRIDES = {
    "momentum_drop_pct": 0.3,
    "score_weight_roe": 2.0,
    "score_weight_div_yield": 2.0,
    "top_n": 30,
    "max_per_industry": 4,
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
    name = "GARP 价值优先(低估值多因子 + 成长 gate)"
    description = (
        "价值优先 GARP:低估值多因子季度调仓为底座(PB≤1 + PE≤30 + 质量 + ROE≥8 + "
        "动量剔除 + 行业上限 + 复合 score),选股前先用成长 gate 把宇宙收敛为「归母净利"
        "同比 ≥ 阈值」的成长股,在便宜且优质的股票里只买仍在成长的。全周期(2010-2026)"
        "年化约 12.1% / 回撤 31.3% / Sharpe 0.59,全维度优于纯价值底座。"
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
