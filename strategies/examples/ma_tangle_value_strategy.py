"""月线均线缠绕价值策略(MaTangleValueStrategy)。

合并 5 个原策略 + PE 两阶段卖出退出(2026-05-24 重构):
- DividendYearsScreener     → utils.dividend.filter_by_dividend_years
- PE 区间筛选               → utils.valuation.filter_by_pe(只看 PE)
- RoeScreener               → utils.financial.filter_by_roe
- MaTangleBreakoutScreener  → utils.kline.detect_ma_tangle_breakout
- MarketCapWeightedBuyer    → utils.composite.MarketCapWeightedBatchBuyer

卖出策略(2026-05-24 PE 两阶段):
- Stage 1(每日):
    - 条件:当前 PE(TTM)> pe_sell_threshold(默认 30,估值过高)
            (PE 缺失视为不满足,保守不卖)
    - 操作:卖出**初始持仓的 15%**
    - 记录参考价 P_ref = 当日 daily bar 的 (high + low) / 2
- Stage 2(每日,Stage 1 之后):
    - 条件:当日 daily close > P_ref * (1 + breakout_pct)(默认 5%)
    - 操作:卖出**初始持仓的 20%**(剩余 65% 持仓持有到结束)
    - 触发后 stage=2 不再判定,并 remove_target 防止再次选入

持仓上限 max_holdings:已持仓达上限时跳过新分批买入。
"""

from strategies.base import Strategy
from strategies.utils import dividend, valuation, financial, kline
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


class MaTangleValueStrategy(Strategy):
    name = "月线均线缠绕价值策略"
    description = (
        "基本面池(连续分红 + PE 区间 + ROE 达标)与月线均线缠绕突破信号交集,"
        "命中后按市值加权 8 周分批买入;PE 高估时分两阶段退出"
        "(PE>30 卖 15% + 记录参考价,后续突破 5% 再卖 20%,剩 65% 持有到底)。"
    )
    frequency = "monthly"
    frequency_overridable = False

    params = {
        # ===== 选股参数 =====
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_min": {"default": 0.0, "type": "float", "label": "PE 下限"},
        "pe_max": {"default": 22.0, "type": "float", "label": "PE 上限"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},
        "ma_fast": {"default": 5, "type": "int", "label": "快速均线"},
        "ma_mid": {"default": 10, "type": "int", "label": "中速均线"},
        "ma_slow": {"default": 20, "type": "int", "label": "慢速均线"},
        "tangle_threshold": {"default": 0.05, "type": "float", "label": "缠绕阈值"},
        "tangle_months": {"default": 2, "type": "int", "label": "缠绕月数"},
        "spread_months": {"default": 6, "type": "int", "label": "发散月数"},
        "spread_threshold": {"default": 0.01, "type": "float", "label": "发散阈值"},
        "vol_red_bars": {"default": 4, "type": "int", "label": "连阳根数"},
        # ===== 仓位 / 买入参数 =====
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 20, "type": "int", "label": "最大持仓只数"},
        # ===== PE 两阶段卖出参数(2026-05-24)=====
        "pe_sell_enabled": {
            "default": True,
            "type": "bool",
            "label": "启用 PE 两阶段卖出",
        },
        "pe_sell_threshold": {
            "default": 30.0,
            "type": "float",
            "label": "Stage 1 PE 阈值(PE 高于此值才卖)",
        },
        "pe_sell_stage1_pct": {
            "default": 0.15,
            "type": "float",
            "label": "Stage 1 卖出比例(初始持仓)",
        },
        "pe_sell_stage2_pct": {
            "default": 0.20,
            "type": "float",
            "label": "Stage 2 卖出比例(初始持仓)",
        },
        "pe_sell_breakout_pct": {
            "default": 0.05,
            "type": "float",
            "label": "Stage 2 突破阈值(P_ref 之上)",
        },
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        # 在 __init__ 内根据参数初始化分批买入器,buy_weeks 可被外部覆盖
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)
        # 卖出状态(per-symbol):
        #   {"stage": 0|1|2, "initial_shares": int, "p_ref": float, "stage1_week": str}
        # stage=0: 未触发(state 不存在亦视为 0)
        # stage=1: Stage 1 已触发,等待 daily close 突破 P_ref*1.05
        # stage=2: Stage 2 已触发,本 symbol 不再卖出
        self._sell_state: dict[str, dict] = {}

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 顺序:廉价数据先,昂贵 K 线后
        pool = dividend.filter_by_dividend_years(
            ctx, symbols, min_years=self.p.min_dividend_years
        )
        pool = valuation.filter_by_pe(
            ctx,
            pool,
            min_value=self.p.pe_min,
            max_value=self.p.pe_max,
        )
        pool = financial.filter_by_roe(ctx, pool, min_roe=self.p.min_roe)
        ctx.log_flow("strategy.fundamental_pool", passed=len(pool))

        signals = []
        for sym in pool:
            if kline.detect_ma_tangle_breakout(
                ctx,
                sym,
                fast=self.p.ma_fast,
                mid=self.p.ma_mid,
                slow=self.p.ma_slow,
                tangle_threshold=self.p.tangle_threshold,
                tangle_months=self.p.tangle_months,
                spread_months=self.p.spread_months,
                spread_threshold=self.p.spread_threshold,
                vol_red_bars=self.p.vol_red_bars,
                freq="monthly",
            ):
                signals.append(sym)
                ctx.log_pass(sym, "strategy.screen.final")

        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(signals))
        return signals

    # ===== 买入:max_holdings 限制由 buyer.step 内自检 =====
    def on_buy(self, ctx):
        # 把 max_holdings 透传给 buyer(buyer 在 _create_buy_plans 时按当前持仓数过滤)
        self._buyer.step(ctx, max_holdings=self.p.max_holdings)

    # ===== 卖出:PE 两阶段(Stage 1 PE 阈值,Stage 2 daily 突破)=====
    def on_sell(self, ctx):
        if not self.p.pe_sell_enabled:
            return

        cur_date = getattr(ctx, "current_date", None)
        if not cur_date:
            return

        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue

            state = self._sell_state.get(sym)
            stage = state["stage"] if state else 0

            if stage == 0:
                self._try_stage1(ctx, sym, shares)
            elif stage == 1:
                self._try_stage2(ctx, sym)
            # stage == 2: 本 symbol 已结束生命周期,跳过

    # ----- Stage 1:PE > 阈值 → 卖 15% + 记录 P_ref -----
    def _try_stage1(self, ctx, sym: str, shares: int) -> None:
        # PE 闸门:PE 缺失视为不满足(保守:数据缺失不卖)
        pe = valuation.get_pe(ctx, sym)
        if pe is None or pe <= float(self.p.pe_sell_threshold):
            return

        # 取当日 daily bar 的 (high+low)/2 作为 P_ref
        daily = ctx.get_price(sym, period="daily")
        if not daily:
            return
        try:
            high = float(daily["high"])
            low = float(daily["low"])
        except (KeyError, TypeError, ValueError):
            return
        p_ref = (high + low) / 2.0

        sell_shares = int(shares * float(self.p.pe_sell_stage1_pct))
        if sell_shares <= 0:
            return
        if sell_shares > shares:
            sell_shares = int(shares)

        ctx.order_shares(sym, -sell_shares)
        self._sell_state[sym] = {
            "stage": 1,
            "initial_shares": int(shares),
            "p_ref": p_ref,
        }
        if hasattr(ctx, "log_exec"):
            ctx.log_exec(
                "sell_signal",
                sym,
                shares=sell_shares,
                price=0.0,
                note=(
                    f"stage1 PE={pe:.2f}>{self.p.pe_sell_threshold:.0f} "
                    f"p_ref={p_ref:.2f} (-15%)"
                ),
            )

    # ----- Stage 2:daily close 突破 P_ref*(1+breakout_pct) → 卖 20% + remove_target -----
    def _try_stage2(self, ctx, sym: str) -> None:
        state = self._sell_state[sym]
        daily = ctx.get_price(sym, period="daily")
        if not daily:
            return
        close = daily.get("close") if isinstance(daily, dict) else None
        if close is None:
            return
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            return

        threshold = float(state["p_ref"]) * (1.0 + float(self.p.pe_sell_breakout_pct))
        if close_f <= threshold:
            return

        sell_shares = int(state["initial_shares"] * float(self.p.pe_sell_stage2_pct))
        if sell_shares <= 0:
            return

        ctx.order_shares(sym, -sell_shares)
        state["stage"] = 2
        if hasattr(ctx, "remove_target"):
            ctx.remove_target(sym)
        if hasattr(ctx, "log_exec"):
            ctx.log_exec(
                "sell_signal",
                sym,
                shares=sell_shares,
                price=close_f,
                note=(
                    f"stage2 close={close_f:.2f} > p_ref*{1 + self.p.pe_sell_breakout_pct:.2f}"
                    f"={threshold:.2f} (-20%)"
                ),
            )
