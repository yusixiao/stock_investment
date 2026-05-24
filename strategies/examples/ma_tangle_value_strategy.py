"""月线均线缠绕价值策略(MaTangleValueStrategy)。

合并 5 个原策略 + MACD 周线分批卖出退出(2026-05-24 更新):
- DividendYearsScreener     → utils.dividend.filter_by_dividend_years
- PePbProductScreener       → utils.valuation.filter_by_pe_pb_product
- RoeScreener               → utils.financial.filter_by_roe
- MaTangleBreakoutScreener  → utils.kline.detect_ma_tangle_breakout
- MarketCapWeightedBuyer    → utils.composite.MarketCapWeightedBatchBuyer

卖出策略(2026-05-24,替代原 PE*PB / 月线 MA 跌破清仓):
- 每周检查:本周 macd_hist > 上周 macd_hist 即视为反转信号
- 每次卖出原始持仓的 25%(按首次触发时的持仓份额计),共 4 批
- 条件持续命中则连续 4 周各卖一批;某周不命中则暂停,下周再判
- 第 4 批一次性卖出全部余量,清仓后从 target pool 移除

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
        "命中后按市值加权 8 周分批买入;持仓在周线 MACD 柱反转时分 4 批 25% 退出。"
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
        "vol_red_bars": {"default": 4, "type": "int", "label": "连阳根数"},
        # ===== 仓位 / 买入参数 =====
        "buy_weeks": {"default": 8, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 20, "type": "int", "label": "最大持仓只数"},
        # ===== MACD 周线分批卖出参数(2026-05-24)=====
        "macd_sell_enabled": {
            "default": True,
            "type": "bool",
            "label": "启用 MACD 分批卖出",
        },
        "macd_sell_batches": {
            "default": 4,
            "type": "int",
            "label": "分批次数(每批 1/N)",
        },
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        # 在 __init__ 内根据参数初始化分批买入器,buy_weeks 可被外部覆盖
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)
        # 卖出状态:{symbol: {"initial_shares": int, "sold_batches": int}}
        # 仅在首次触发卖出时建档,清仓后清除
        self._sell_state: dict[str, dict] = {}
        # 周线 cadence 自检:记录上次执行 on_sell 的周键,避免同周内重复触发
        self._last_sell_week_key: str | None = None

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

    # ===== 卖出:周线 MACD 柱反转 → 分批 25% 卖出 =====
    def on_sell(self, ctx):
        if not self.p.macd_sell_enabled:
            return

        # 周线 cadence:同一周内只触发一次
        cur_date = getattr(ctx, "current_date", None)
        if not cur_date:
            return
        wk = _week_key(cur_date)
        if wk == self._last_sell_week_key:
            return
        self._last_sell_week_key = wk

        batches = max(1, int(self.p.macd_sell_batches or 4))
        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue

            # 读取最近 2 根周线 macd_hist:本周 vs 上周
            series = kline.get_macd_hist_series(ctx, sym, n=2, freq="weekly")
            if series is None or len(series) < 2:
                continue
            prev_hist, cur_hist = series[-2], series[-1]
            # 判定:本周 > 上周 即视为反转信号
            if not (cur_hist > prev_hist):
                continue

            # 建档(首次触发):锁定原始持仓份额
            state = self._sell_state.get(sym)
            if state is None:
                state = {"initial_shares": int(shares), "sold_batches": 0}
                self._sell_state[sym] = state

            initial = state["initial_shares"]
            sold_batches = state["sold_batches"]
            remaining_batches = batches - sold_batches
            if remaining_batches <= 0:
                # 已经全部卖完,清理状态(理论上 shares=0 时也不会到这里)
                self._sell_state.pop(sym, None)
                continue

            # 最后一批:把剩余全部卖掉,避免浮点 / 取整残留
            is_last_batch = remaining_batches == 1
            if is_last_batch:
                sell_shares = int(shares)
            else:
                sell_shares = int(initial * (1.0 / batches))
                # 防御:不能超过当前剩余
                if sell_shares > shares:
                    sell_shares = int(shares)
                # 至少 1 股,否则视为持仓太少无法分批
                if sell_shares <= 0:
                    self._sell_state.pop(sym, None)
                    continue

            ctx.order_shares(sym, -sell_shares)
            state["sold_batches"] = sold_batches + 1
            if hasattr(ctx, "log_exec"):
                ctx.log_exec(
                    "sell_signal",
                    sym,
                    shares=sell_shares,
                    price=0.0,
                    note=(
                        f"macd_hist {prev_hist:.4f}→{cur_hist:.4f} "
                        f"batch {state['sold_batches']}/{batches}"
                    ),
                )

            if is_last_batch:
                # 清仓:从 target pool 移除并清除 sell_state
                if hasattr(ctx, "remove_target"):
                    ctx.remove_target(sym)
                self._sell_state.pop(sym, None)
