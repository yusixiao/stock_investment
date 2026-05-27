"""现金流保守策略 — 粗算回报率版(ConservativeRoughStrategy)。

⚠️ 重要边界(2026-05-27):
本策略**只**实现 cpa 框架因子2 "粗算 R"(R = NP × M × (1−Q) / 市值),
**不**实现需要 LLM 11 步精算的真实 GG / KK。
完整 cpa 流程见 `backend/services/agent/agents/cpa/prompts/phase3_quantitative.md`。

设计动机:
cpa Agent 个股深度分析的精算 GG 不可机械化(每步都需 LLM 对会计政策、
行业特征、附注披露做定性判断)。本策略退而求其次,用机械化可计算的
**粗算 R + Layer 2 否决项**做股票池筛选,用于:
1. 给 cpa Agent 提供候选股票池(reduce 全 A 股 5400+ → 几十只)
2. 作为基线对比 cpa LLM 真实结果的差异

选股管线(顺序优化:廉价数据先,昂贵 history 后):
  1) 金融股排除(直接整类排除,cpa 框架对金融业有方法论盲点)
  2) 连续分红年限 >= min_dividend_years(稳定派息文化)
  3) 粗算 R >= r_threshold_pct(默认 4.7+0.5=5.2pct)
  4) 商誉 / 归母权益 <= max_goodwill_ratio(默认 30%)
  5) 净现金 = 货币资金 − 总负债 >= 0
  6) 近 2 年年报 FCF 不全为负

买入:复用 MarketCapWeightedBatchBuyer(市值加权 N 周分批),与价值三因子
策略保持公平对比口径。
"""

from strategies.base import Strategy
from strategies.utils import dividend
from strategies.utils import conservative
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


class ConservativeRoughStrategy(Strategy):
    name = "现金流保守策略(粗算)"
    description = (
        "基于 cpa 框架因子2 粗算穿透回报率 R(机械化计算)+ 4 项 Layer 2 否决,"
        "排除金融股 / 高商誉 / 净现金转负 / FCF 持续为负;"
        "命中后按市值加权分批买入。"
        "注意:不等于 cpa Agent 精算 KK,见模块文档。"
    )
    frequency = "monthly"
    frequency_overridable = False

    params = {
        # ===== 选股参数 =====
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "r_threshold_pct": {
            "default": conservative.THRESHOLD_A_PCT
            + conservative.DEFAULT_SAFETY_MARGIN_PCT,
            "type": "float",
            "label": "R 门槛(% A 股 II=4.7 + 安全边际 0.5)",
        },
        "max_goodwill_ratio": {
            "default": 0.30,
            "type": "float",
            "label": "商誉/归母权益 上限",
        },
        # ===== 仓位 / 买入参数 =====
        "buy_weeks": {"default": 4, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 15, "type": "int", "label": "最大持仓只数"},
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 1) 金融股排除(O(N) 单字段读取,最廉价)
        pool = conservative.reject_financial_industry(ctx, symbols)

        # 2) 连续分红年限(分红表已 memoize,廉价)
        pool = dividend.filter_by_dividend_years(
            ctx, pool, min_years=self.p.min_dividend_years
        )

        # 3) 粗算 R(需要 history + price,稍贵)
        pool = conservative.filter_by_r(ctx, pool, threshold_pct=self.p.r_threshold_pct)

        # 4-6) Layer 2 否决项
        pool = conservative.reject_high_goodwill(
            ctx, pool, max_ratio=self.p.max_goodwill_ratio
        )
        pool = conservative.reject_negative_net_cash(ctx, pool)
        pool = conservative.reject_negative_fcf_2y(ctx, pool)

        for sym in pool:
            ctx.log_pass(sym, "strategy.screen.final")
        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(pool))
        return pool

    def on_buy(self, ctx):
        self._buyer.step(ctx, max_holdings=self.p.max_holdings)

    def on_sell(self, ctx):
        # v1 永久持有(回测期内不主动卖出)。后续可加 R 跌破阈值退出。
        return
