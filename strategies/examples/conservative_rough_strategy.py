"""现金流保守策略 — 粗算回报率版(ConservativeRoughStrategy)。

⚠️ 重要边界(2026-05-27):
本策略**只**实现 cpa 框架因子2 "粗算 R"(R = NP × M × (1−Q) / 市值),
**不**实现需要 LLM 11 步精算的真实 GG / KK。
完整 cpa 流程见 `backend/services/agent/agents/cpa/prompts/phase3_quantitative.md`。

设计动机:
cpa Agent 个股深度分析的精算 GG 不可机械化(每步都需 LLM 对会计政策、
行业特征、附注披露做定性判断)。本策略退而求其次,用机械化可计算的
**粗算 R + Layer 2 否决项 + L1.3 信誉评级 + L3 仓位矩阵**做股票池筛选,
用于:
1. 给 cpa Agent 提供候选股票池(reduce 全 A 股 5400+ → 几十只)
2. 作为基线对比 cpa LLM 真实结果的差异

选股管线(顺序优化:廉价数据先,昂贵 history 后):
  1) 金融股排除(始终硬否决)
  2) 连续分红年限 >= min_dividend_years
  3) 粗算 R >= r_threshold_pct(默认 4.7+0.5=5.2pct)
  4-7) Layer 2 否决 — 硬否决 vs 软评分双模式(use_trap_rating_soft)
  8) L2.5 trap_rating 记录(供 L3 仓位矩阵)
  9) L1.3 信誉评级记录(供 L3 仓位矩阵)
 10) L3 仓位矩阵:始终启用,只保留 full / p70 tier,observe / skip 出局

买入(2026-05-28 重写为 CPA 原口径):
  CpaTierBatchBuyer 按 tier 分配单股目标仓位:
    full → max_per_stock_pct × 100%
    p70  → max_per_stock_pct × 70%
  N 周等额爬坡,逐周 order_target_percent 到累积目标。
  抛弃了 MarketCapWeightedBatchBuyer 的市值加权机制,改用 CPA tier-based 单股配比。

卖出(2026-05-28 重写为 CPA 原口径):
  CPA 7 条结构化止损规则(`phase3_valuation.md` §10.2):
    critical → 清仓(净现金<0 / FCF yield<5% / FCF 连负 2 期)
    warning  → 减仓到 50%(D/E恶化 / 营收同比<-20% / 毛利率恶化 / 支付率降>30%)
  warning 类按"每个 reason 触发一次减半"(避免每根 bar 都减半导致流氓清仓)。
  入场时记录 baseline(D/E、毛利率、payout)供规则 4/6/7 对比。
"""

from strategies.base import Strategy
from strategies.utils import conservative
from strategies.utils import conservative_sell
from strategies.utils import dividend
from strategies.utils.composite.cpa_tier_batch_buyer import CpaTierBatchBuyer


class ConservativeRoughStrategy(Strategy):
    name = "现金流保守策略(粗算)"
    description = (
        "基于 cpa 框架因子2 粗算穿透回报率 R(机械化计算)+ 5 项 Layer 2 否决,"
        "排除金融股 / 高商誉 / 净现金转负 / FCF 持续为负 / ROE 三年下降>30%;"
        "L1.3 信誉评级 + L2.5 trap_rating + L3 仓位矩阵(full/p70 tier);"
        "CPA tier-based 单股配比分批买入 + CPA 7 条基本面止损。"
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
        "max_roe_decline": {
            "default": 0.30,
            "type": "float",
            "label": "ROE 三年相对降幅上限",
        },
        "use_trap_rating_soft": {
            "default": False,
            "type": "bool",
            "label": "L2.5 软评分模式(剔除 high 而非逐项硬否决)",
        },
        # ===== 仓位 / 买入参数 =====
        "max_per_stock_pct": {
            "default": 0.20,
            "type": "float",
            "label": "单股仓位绝对上限(full tier 100% × 此值)",
        },
        "buy_weeks": {"default": 4, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 15, "type": "int", "label": "最大持股只数"},
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        self._buyer = CpaTierBatchBuyer(
            max_per_stock_pct=self.p.max_per_stock_pct,
            buy_weeks=self.p.buy_weeks,
        )
        # 入场时点 baseline:{symbol: {"debt_equity", "gross_margin", "payout"}}
        self._entry_baselines: dict[str, dict] = {}
        # 已触发 warning 的规则集合:{symbol: set(reason_id)},去重避免每根 bar 重复减仓
        self._warning_seen: dict[str, set[str]] = {}

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 1) 金融股排除
        pool = conservative.reject_financial_industry(ctx, symbols)

        # 2) 连续分红年限
        pool = dividend.filter_by_dividend_years(
            ctx, pool, min_years=self.p.min_dividend_years
        )

        # 3) 粗算 R
        pool = conservative.filter_by_r(ctx, pool, threshold_pct=self.p.r_threshold_pct)

        # 4-6) CPA critical 三条 — 始终硬过滤(soft 也不豁免)
        # 入场后 on_sell critical 规则 1/2/3 会立即清仓,screen 必须先过滤
        # 否则注定买入即清仓,产生"持仓 1 天"的虚假交易
        pool = conservative.reject_negative_net_cash(ctx, pool)
        pool = conservative.reject_negative_fcf_2y(ctx, pool)
        pool = conservative.reject_low_fcf_yield(ctx, pool)

        # 7-8) Layer 2 软陷阱(高商誉 / ROE 退坡)— 硬否决 vs 软评分双模式
        # 这两项 CPA 7 条原文无对应止损规则,作为价值陷阱辅助信号,允许 soft 放宽
        if self.p.use_trap_rating_soft:
            soft_pool: list[str] = []
            for sym in pool:
                triggered: list[str] = []
                # NOTE: _is_goodwill_triggered 内部硬编码 30% 阈值,与默认 param 对齐
                if conservative._is_goodwill_triggered(ctx, sym):
                    triggered.append("goodwill")
                if conservative._is_roe_decline_3y_triggered(
                    ctx, sym, max_decline=self.p.max_roe_decline
                ):
                    triggered.append("roe_decline")
                # 2 项里命中 ≥2(全部)→ high 拒;≤1 → 通过
                rating = (
                    "high"
                    if len(triggered) >= 2
                    else ("mid" if len(triggered) == 1 else "low")
                )
                if rating == "high":
                    ctx.log_reject(
                        sym,
                        "conservative.trap_soft",
                        "trap_rating_high",
                        triggered=triggered,
                    )
                else:
                    ctx.log_pass(
                        sym,
                        "conservative.trap_soft",
                        rating=rating,
                        triggered=triggered,
                    )
                    soft_pool.append(sym)
            ctx.log_flow(
                "conservative.trap_soft", input=len(pool), passed=len(soft_pool)
            )
            pool = soft_pool
        else:
            pool = conservative.reject_high_goodwill(
                ctx, pool, max_ratio=self.p.max_goodwill_ratio
            )
            pool = conservative.reject_roe_decline_3y(
                ctx, pool, max_decline=self.p.max_roe_decline
            )

        # 8) L2.5 trap_rating 记录
        conservative.record_trap_rating(
            ctx, pool, max_roe_decline=self.p.max_roe_decline
        )

        # 9) L1.3 信誉评级
        conservative.record_credibility_factors(ctx, pool)

        # 10) L3 仓位矩阵 — 始终启用,只保留 full + p70
        pool = conservative.record_position_tier(ctx, pool, include_observe=False)

        for sym in pool:
            ctx.log_pass(sym, "strategy.screen.final")
        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(pool))
        return pool

    def on_buy(self, ctx):
        # 1) 为新晋 symbols 记录入场 baseline(去重)
        for sym in getattr(ctx, "new_symbols", []) or []:
            if sym not in self._entry_baselines:
                self._entry_baselines[sym] = conservative_sell.record_entry_baseline(
                    ctx, sym
                )
        # 2) 执行分批买入
        self._buyer.step(ctx, max_holdings=self.p.max_holdings)

    def on_sell(self, ctx):
        """CPA 7 条基本面止损规则:critical → 清仓;warning → 减仓到 50%。

        warning 仅在新规则首次触发时减半(`_warning_seen[sym]` 去重),
        避免每根 bar 都减半导致 runaway 清仓。
        """
        positions = ctx.get_positions()
        for sym, pos in list(positions.items()):
            shares = getattr(pos, "shares", 0)
            if shares <= 0:
                continue

            baseline = self._entry_baselines.get(sym)
            severity, reasons = conservative_sell.cpa_fundamental_stop_loss(
                ctx, sym, baseline
            )

            if severity == "critical":
                ctx.order_shares(sym, -shares)
                ctx.remove_target(sym)
                self._entry_baselines.pop(sym, None)
                self._warning_seen.pop(sym, None)
                ctx.log_reject(
                    sym,
                    "conservative.stop_loss",
                    "critical",
                    reasons=reasons,
                    shares=shares,
                )
                continue

            if severity == "warning":
                seen = self._warning_seen.setdefault(sym, set())
                new_reasons = [r for r in reasons if r not in seen]
                if not new_reasons:
                    continue  # 全部规则都已减半过,本 bar 不再动作
                # 出现新 warning reason → 再减半一次(每个 reason 触发一次)
                halved = shares // 2
                if halved > 0:
                    ctx.order_shares(sym, -halved)
                seen.update(new_reasons)
                ctx.log_reject(
                    sym,
                    "conservative.stop_loss",
                    "warning",
                    reasons=new_reasons,
                    shares=shares,
                    halved=halved,
                )
