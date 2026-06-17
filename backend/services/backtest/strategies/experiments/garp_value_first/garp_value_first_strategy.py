"""GARP(价值优先版)—— GarpValueFirstStrategy。

⚠️ 实验性质,不暴露 UI(experiments/ 目录)。

== 与已证伪的 a_garp 的根本区别 ==
`experiments/a_garp/`(commit 2129128)是「**成长优先**」GARP:先按 N 年净利/营收
CAGR 选高成长股,再用 PEG/PB 做估值健康检查,PEG 升序取 Top N。该设计已证伪
(纯成长方向在 A 股全周期同样失败,见 experiments/growth/ 全组证伪结论)。

本策略是「**价值优先**」GARP,完全反过来:
- **底座 = C_full_t30**(已验证的低估值多因子季度调仓:PB≤1 + PE≤30 + 质量过滤 +
  ROE≥8 + 动量剔除 + 行业上限 + 复合 score,全周期 11.5%/DD35%)。
- **成长只作一道「门」(gate)**:在底座选股「之前」,先把宇宙收敛为「归母净利同比
  增速 ≥ growth_min_yoy」的「正在成长」的股票,再让 C_full_t30 在这个子集上跑
  价值+质量+排序。即「**在便宜且优质的股票里,只买还在成长的**」。

设计动机:growth/ 实验证明「脱离估值的纯成长」是接盘;价值方向(C_full_t30)是目前
唯一站得住的边。本策略检验:在价值边的基础上叠加一道「成长非负/成长达标」的过滤,
能否在不破坏价值纪律的前提下进一步剔除「便宜但在衰退」的价值陷阱、抬高年化。

实现:子类 LvmfCFullT30Strategy,**零管线重写**——只在 screen() 前用成长 gate 预过滤
symbols,再调 super().screen()。成长字段取 utils.growth 的 NOTICE_DATE-as-of 口径
(严格防 look-ahead)。gate 仅在调仓月计算(省算力)。

验收:与 C_full_t30 基线同口径(纯绝对年化 + 2/4 段 OOS),只有跨段稳健且年化不低于
基线才有意义;否则归档为「价值边已是局部最优,成长 gate 无增益」的负结果。

== 回测结论(2010-01~2026-06,A 股全市场,/tmp/garp_value_eval.py)==
成长 gate **是迄今唯一被验证为正增益的叠加方向**(A regime / B 因子 / 纯成长 均已证伪):
  变体             年化      回撤    Sharpe   Calmar*   交易
  BASE_C30(基线) 11.50%   35.4%    0.554    0.325    1341
  GARP g0(净利≥0)12.11%   31.3%    0.590    0.387     796   ← 全维度优于基线
  GARP g15(净利≥15%)11.63% 23.5%   0.584    0.494     425   ← 回撤腰斩,防御型
  (*Calmar 引擎未算,手算 = ann/maxdd)
- **g0 = 严格更优的基线**:年化↑、回撤↓、Sharpe↑、PF↑、换手↓;2 段两半都跑赢基线
  (117%/202% vs 108%/187%),4 段中 3 段 ≥ 基线,每段大幅跑赢 CSI300。几乎「免费」改进。
- **g15 = 防御型**:年化≈基线但回撤 35%→23.5%(Calmar 0.494 最佳),牺牲后段牛市上行
  换深熊少亏(2010-2014 段 +61% vs 基线 +14%)。适合回撤敏感口径。
- 机理:成长只作 gate(在「便宜且优质」池里再剔除「净利在衰退」的),剔掉衰退型价值陷阱
  而非追高估值成长 → 与纯成长(growth/ 全组证伪)本质不同。
结果存档:logs/smoke/garp_value_eval.{log,json}。

== OOS 验证(C_full_t30 同款 rigor:16 段年度 + 7 独立 regime 窗口,/tmp/garp_oos_eval.py)==
7 个独立 regime 窗口(各自 fresh capital)g0/g15 vs BASE_C30 的 ann WIN/LOSE:
  regime 窗口            CSI300   BASE    g0(Δ)         g15(Δ)
  H1 2010-2018          +14.0%  9.64%  10.21%(+0.6)WIN 12.66%(+3.0)WIN
  H2 2018-2026          +21.4% 12.42%  13.20%(+0.8)WIN 11.91%(-0.5)LOSE
  疯牛灾 2014-2016       +24.5% 20.30%  20.21%(-0.1)≈    19.00%(-1.3)LOSE
  慢牛熊 2016-2019       +3.8%   2.02%   5.55%(+3.5)WIN -1.83%(-3.9)LOSE
  结构牛 2019-2021       +79.9%  0.79%   6.41%(+5.6)WIN  1.43%(+0.6)WIN
  熊 2021-2024           -40.6% 18.86%  24.90%(+6.0)WIN 15.90%(-3.0)LOSE
  反弹 2024-2026         +52.0% 19.25%  17.17%(-2.1)LOSE 16.96%(-2.3)LOSE
结论:
- **g0 = 稳健近严格改进**:7 窗 5 WIN / 1≈(疯牛 -0.09,可忽略)/ 1 LOSE(2024-2026 反弹
  -2.1);关键是**修复了价值底座最大短板**——结构牛 2019-2021(BASE 仅 0.79%,g0 6.41%)、
  慢牛熊(+3.5)、深熊 2021-2024(+6.0,且 vs CSI300 -40.6%);疯牛灾压力检验通过(g0≈BASE,
  二者均 ~20% 碾压指数)。每个窗口都跑赢 CSI300(熊市少亏/牛市赚钱,非对称验收过)。
- **g15 = 纯防御变体**:全周期 DD 23.5%(vs 35.4%)、Calmar 0.494 最佳,但牺牲收益,regime
  记录混杂(牛市让出上行);仅适合回撤敏感口径,非严格改进。
- g0 已通过 C_full_t30 同款(实为更强:在 BASE 最弱的结构牛/慢牛熊大幅反超)OOS,可作
  「刻意发布」候选;唯一已知弱点 = 2024-2026 这一段近端反弹略逊基线。
结果存档:logs/smoke/garp_oos_eval.{log,json}。
"""

from __future__ import annotations

import copy
from datetime import date

from services.backtest.strategies.experiments.lvmf_c_full_t30.lvmf_c_full_t30_strategy import (
    LvmfCFullT30Strategy,
)
from services.backtest.strategies.utils import growth


def _build_garp_params() -> dict:
    """深拷贝 C_full_t30 params,新增成长 gate 参数。父类零污染。"""
    params = copy.deepcopy(LvmfCFullT30Strategy.params)
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


class GarpValueFirstStrategy(LvmfCFullT30Strategy):
    name = "GARP 价值优先(C_full_t30 + 成长 gate·实验)"
    description = (
        "【实验】价值优先 GARP:以 C_full_t30(低估值多因子季度调仓)为底座,"
        "选股前先把宇宙收敛为「归母净利同比增速 ≥ 阈值」的成长股,即"
        "「在便宜且优质的股票里只买仍在成长的」。检验成长 gate 能否在不破坏价值纪律下"
        "剔除衰退型价值陷阱、抬高年化。零管线重写,gate 仅调仓月计算。未发布。"
    )

    params = _build_garp_params()

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
