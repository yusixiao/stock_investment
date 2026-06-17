"""C_full_t30 —— 低估值多因子季度调仓的「全周期调优配置」实验固化版。

⚠️ 实验性质,不暴露 UI(experiments/ 目录)。这是对已发布
`LowValuationMultiFactorQuarterlyStrategy` 跑组合矩阵(/tmp/lvmf_combo.py)
择优出来的一组默认参数,**本质是 best-of-N 选择,带软过拟合风险**,故不直接
改 deployed 的 shipped 默认值,而以子类 + 固化参数的形式留存,供进一步验证 /
将来若决定发布时参考。

== 配置(相对 deployed 默认值的改动)==
    momentum_drop_pct      0.2  -> 0.3    剔最差 30% 动量
    score_weight_roe       1.0  -> 2.0
    score_weight_div_yield 1.0  -> 2.0
    top_n                  15   -> 30
    max_per_industry       3    -> 4
    rebalance_months  [5,9,11] -> [3,6,9,12]  规整季度调仓

== 回测结论(2010-01 ~ 2026-06,A 股全市场)==
    全周期年化 11.50% / 最大回撤 35.4% / Sharpe 0.554 / Calmar 0.325
    OOS 分段验证(/tmp/lvmf_validate.py):6 WIN / 1 LOSE
      - 两半段均跑赢 deployed 默认(H1 9.64% vs 8.12%、H2 12.42% vs 10.26%)
      - 唯一 LOSE = 2014-2015 疯牛(分散 + 动量过滤封顶上行,属风格特征非过拟合)
    已证伪的叠加方向(不要重复探索):
      - 大盘 regime 择时(CSI300 SMA200):年化腰斩至 5.74%,与深价值逆周期冲突
      - 逆动量 / 穿透回报率 R 因子:全周期年化、回撤、Sharpe 全面劣于本配置

== 复现 ==
    全周期:/tmp/lvmf_baseline.py | OOS 分段:/tmp/lvmf_validate.py
    结果存档:logs/smoke/lvmf_{baseline,validate,combo}.{log,json}
"""
import copy

from services.backtest.strategies.deployed.low_valuation_multifactor_quarterly_strategy import (
    LowValuationMultiFactorQuarterlyStrategy,
)


# C_full_t30 相对父类默认值的覆盖项
_C_FULL_T30_OVERRIDES = {
    "momentum_drop_pct": 0.3,
    "score_weight_roe": 2.0,
    "score_weight_div_yield": 2.0,
    "top_n": 30,
    "max_per_industry": 4,
    "rebalance_months": [3, 6, 9, 12],
}


def _build_params() -> dict:
    """深拷贝父类 params,只 patch C_full_t30 的 default,标签/类型全继承。"""
    params = copy.deepcopy(LowValuationMultiFactorQuarterlyStrategy.params)
    for key, default in _C_FULL_T30_OVERRIDES.items():
        if key in params:
            params[key]["default"] = default
    return params


class LvmfCFullT30Strategy(LowValuationMultiFactorQuarterlyStrategy):
    name = "低估值多因子季度调仓(C_full_t30 全周期调优·实验)"
    description = (
        "【实验】对低估值多因子季度调仓跑组合矩阵择优的固化配置:"
        "动量剔除 30%、ROE/股息率权重 2.0、持 top30、单行业≤4、季度调仓 [3,6,9,12]。"
        "全周期(2010-2026)年化约 11.5% / 回撤 35.4%,OOS 6/7 区间跑赢 deployed 默认。"
        "best-of-N 择优带软过拟合风险,留存待进一步验证,未发布。"
    )

    params = _build_params()
