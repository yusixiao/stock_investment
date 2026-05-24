"""月线均线缠绕价值策略(MaTangleValueStrategy)。

合并 5 个原策略 + MACD 周线两阶段卖出退出(2026-05-24 重构):
- DividendYearsScreener     → utils.dividend.filter_by_dividend_years
- PePbProductScreener       → utils.valuation.filter_by_pe_pb_product
- RoeScreener               → utils.financial.filter_by_roe
- MaTangleBreakoutScreener  → utils.kline.detect_ma_tangle_breakout
- MarketCapWeightedBuyer    → utils.composite.MarketCapWeightedBatchBuyer

卖出策略(2026-05-24 两阶段重构):
- Stage 1(每周一次,周线 cadence):
    - 条件:本周 weekly macd_hist < 上周 weekly macd_hist(动能减弱)
            **且** 当前 PE(TTM)> macd_sell_pe_min(默认 20,估值偏高)
            (PE 缺失视为不满足,保守不卖)
    - 操作:卖出**初始持仓的 15%**
    - 记录参考价 P_ref = 当周 weekly bar 的 (high + low) / 2
- Stage 2(每日,Stage 1 之后):
    - 条件:当日 daily close > P_ref * (1 + breakout_pct)(默认 5%)
    - 操作:卖出**初始持仓的 20%**(剩余 65% 持仓)
    - 触发后 stage=2 不再判定,并 remove_target 防止再次选入

持仓上限 max_holdings:已持仓达上限时跳过新分批买入。
"""

from strategies.base import Strategy
from strategies.utils import dividend, valuation, financial, kline
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


# 项目约定:周键(ISO 年-周)用于 weekly cadence 自检
def _week_key(date_str: str) -> str:
    """date "YYYY-MM-DD" → ISO 周键 "YYYY-Www"。失败返回原字符串(防呆)。"""
    try:
        from datetime import date as _date

        d = _date.fromisoformat(date_str)
        yr, wk, _ = d.isocalendar()
        return f"{yr}-W{wk:02d}"
    except Exception:
        return date_str or ""


class MaTangleValueStrategy(Strategy):
    name = "月线均线缠绕价值策略"
    description = (
        "基本面池(连续分红 + PE*PB 区间 + ROE 达标)与月线均线缠绕突破信号交集,"
        "命中后按市值加权 8 周分批买入;持仓在周线 MACD 柱减弱时分两阶段退出"
        "(Stage 1 卖 15% + 记录参考价,Stage 2 突破 5% 时再卖 20%)。"
    )
    frequency = "monthly"
    frequency_overridable = False

    params = {
        # ===== 选股参数 =====
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_pb_min": {"default": 0.0, "type": "float", "label": "PE*PB 下限"},
        "pe_pb_max": {"default": 22.0, "type": "float", "label": "PE*PB 上限"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},
        "ma_fast": {"default": 5, "type": "int", "label": "快速均线"},
        "ma_mid": {"default": 10, "type": "int", "label": "中速均线"},
        "ma_slow": {"default": 20, "type": "int", "label": "慢速均线"},
        "tangle_threshold": {"default": 0.05, "type": "float", "label": "缠绕阈值"},
        "tangle_months": {"default": 2, "type": "int", "label": "缠绕月数"},
        "spread_months": {"default": 6, "type": "int", "label": "发散月数"},
        "spread_threshold": {"default": 0.01, "type": "float", "label": "发散阈值"},
        "macd_red_bars": {"default": 4, "type": "int", "label": "MACD 连续红柱根数"},
        # ===== 仓位 / 买入参数 =====
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 20, "type": "int", "label": "最大持仓只数"},
        # ===== MACD 周线两阶段卖出参数(2026-05-24)=====
        "macd_sell_enabled": {
            "default": True,
            "type": "bool",
            "label": "启用 MACD 两阶段卖出",
        },
        "macd_sell_stage1_pct": {
            "default": 0.15,
            "type": "float",
            "label": "Stage 1 卖出比例(初始持仓)",
        },
        "macd_sell_stage2_pct": {
            "default": 0.20,
            "type": "float",
            "label": "Stage 2 卖出比例(初始持仓)",
        },
        "macd_sell_breakout_pct": {
            "default": 0.05,
            "type": "float",
            "label": "Stage 2 突破阈值(P_ref 之上)",
        },
        "macd_sell_pe_min": {
            "default": 20.0,
            "type": "float",
            "label": "Stage 1 PE 下限(PE 高于此值才卖)",
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
        pool = valuation.filter_by_pe_pb_product(
            ctx,
            pool,
            min_value=self.p.pe_pb_min,
            max_value=self.p.pe_pb_max,
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
                macd_red_bars=self.p.macd_red_bars,
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

    # ===== 卖出:MACD 两阶段(Stage 1 周线,Stage 2 daily 突破)=====
    def on_sell(self, ctx):
        if not self.p.macd_sell_enabled:
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
                self._try_stage1(ctx, sym, shares, cur_date)
            elif stage == 1:
                self._try_stage2(ctx, sym)
            # stage == 2: 本 symbol 已结束生命周期,跳过

    # ----- Stage 1:周线 macd_hist 减弱 → 卖 15% + 记录 P_ref -----
    def _try_stage1(self, ctx, sym: str, shares: int, cur_date: str) -> None:
        # 周线 cadence 自检(per-symbol):同一 ISO 周内只评估一次
        wk = _week_key(cur_date)

        series = kline.get_macd_hist_series(ctx, sym, n=2, freq="weekly")
        if series is None or len(series) < 2:
            return
        prev_hist, cur_hist = series[-2], series[-1]
        # 动能减弱:本周 hist < 上周 hist
        if not (cur_hist < prev_hist):
            return

        # PE 闸门:仅当 PE > 下限时才卖出(估值偏高 + 动能减弱才退出);
        # PE 缺失视为不满足(保守:数据缺失不卖)
        pe = valuation.get_pe(ctx, sym)
        if pe is None or pe <= float(self.p.macd_sell_pe_min):
            return

        # 取当周 weekly bar 的 (high+low)/2 作为 P_ref
        bars = ctx.get_history(sym, 1, period="weekly")
        if not bars:
            return
        last_bar = bars[-1]
        try:
            p_ref = (float(last_bar["high"]) + float(last_bar["low"])) / 2.0
        except (KeyError, TypeError, ValueError):
            return

        sell_shares = int(shares * float(self.p.macd_sell_stage1_pct))
        if sell_shares <= 0:
            return
        if sell_shares > shares:
            sell_shares = int(shares)

        ctx.order_shares(sym, -sell_shares)
        self._sell_state[sym] = {
            "stage": 1,
            "initial_shares": int(shares),
            "p_ref": p_ref,
            "stage1_week": wk,
        }
        if hasattr(ctx, "log_exec"):
            ctx.log_exec(
                "sell_signal",
                sym,
                shares=sell_shares,
                price=0.0,
                note=(
                    f"stage1 macd_hist {prev_hist:.4f}→{cur_hist:.4f} "
                    f"p_ref={p_ref:.2f} (-15%)"
                ),
            )

    # ----- Stage 2:daily close 突破 P_ref*1.05 → 卖 20% + remove_target -----
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

        threshold = float(state["p_ref"]) * (1.0 + float(self.p.macd_sell_breakout_pct))
        if close_f <= threshold:
            return

        sell_shares = int(state["initial_shares"] * float(self.p.macd_sell_stage2_pct))
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
                    f"stage2 close={close_f:.2f} > p_ref*{1 + self.p.macd_sell_breakout_pct:.2f}"
                    f"={threshold:.2f} (-20%)"
                ),
            )
