"""价值三因子 + 月线突破择时策略(ValueFactorBreakoutStrategy)。

设计动机(2026-05-23):
基于 MaTangleValueStrategy 诊断报告(exported/ma_tangle_diag_*_overview.md):
- 月线均线缠绕信号(D4 纯信号)= -2.52% 年化,实证为负 alpha
- 越加价值约束效果越好(D0 > D2 > D3 > D4)→ 价值因子才是 alpha 来源
本策略移除负贡献的 tangle 信号,改用极简的「close > MA20」月线突破作择时,
保留全部价值三因子(分红 + 估值 + ROE)。

选股管线:
  1) 连续分红年限 >= min_dividend_years
  2) PE * PB ∈ [pe_pb_min, pe_pb_max]
  3) ROE >= min_roe (%)
  4) 最近月收盘 > MA(ma_window)            ← 唯一择时条件

买入:复用 MarketCapWeightedBatchBuyer(市值加权 N 周分批),保持与 D0 公平对比。
卖出(可选,任一命中清仓):
  - sell_pe_pb_max > 0:估值过热
  - sell_below_ma ∈ {ma10/ma20/ma30}:月线趋势破位
"""

from strategies.base import Strategy
from strategies.utils import dividend, valuation, financial, kline
from strategies.utils.composite.market_cap_weighted_batch_buyer import (
    MarketCapWeightedBatchBuyer,
)


class ValueFactorBreakoutStrategy(Strategy):
    name = "价值三因子月线突破策略"
    description = (
        "基本面池(连续分红 + PE*PB 区间 + ROE 达标)与「月收盘 > MA(N)」"
        "突破信号交集,命中后按市值加权分批买入;支持 PE*PB / 月线 MA 退出。"
    )
    frequency = "monthly"
    frequency_overridable = False

    params = {
        # ===== 选股参数(价值三因子)=====
        "min_dividend_years": {"default": 5, "type": "int", "label": "最少分红年数"},
        "pe_pb_min": {"default": 0.0, "type": "float", "label": "PE*PB 下限"},
        "pe_pb_max": {"default": 22.0, "type": "float", "label": "PE*PB 上限"},
        "min_roe": {"default": 10.0, "type": "float", "label": "最低 ROE(%)"},
        # ===== 择时参数 =====
        # ma_window=0 表示关闭择时(纯价值池,作 V0 基线对比用)
        "ma_window": {
            "default": 20,
            "type": "int",
            "label": "突破 MA 窗口(0=关闭择时)",
        },
        # ===== 仓位 / 买入参数 =====
        "buy_weeks": {"default": 4, "type": "int", "label": "分批周数"},
        "max_holdings": {"default": 15, "type": "int", "label": "最大持仓只数"},
        # ===== 卖出参数 =====
        "sell_pe_pb_max": {
            "default": 0.0,
            "type": "float",
            "label": "PE*PB 退出阈值(0=关)",
        },
        "sell_below_ma": {
            "default": "none",
            "type": "str",
            "label": "月线 MA 退出(none/ma10/ma20/ma30)",
        },
    }

    def __init__(self, param_overrides=None):
        super().__init__(param_overrides)
        self._buyer = MarketCapWeightedBatchBuyer(buy_weeks=self.p.buy_weeks)

    def screen(self, ctx, symbols):
        ctx.log_flow("strategy.screen.start", input=len(symbols))

        # 顺序:廉价数据先(分红→估值→财务),最后做 K 线择时
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

        # 择时:ma_window > 0 时启用 close > MA 过滤;否则直接返回价值池(V0 基线)
        if self.p.ma_window and self.p.ma_window > 0:
            pool = kline.filter_by_close_above_ma(
                ctx, pool, ma_window=self.p.ma_window, freq="monthly"
            )

        for sym in pool:
            ctx.log_pass(sym, "strategy.screen.final")
        ctx.log_flow("strategy.screen.done", input=len(symbols), passed=len(pool))
        return pool

    def on_buy(self, ctx):
        # max_holdings 由 buyer.step 内自检
        self._buyer.step(ctx, max_holdings=self.p.max_holdings)

    def on_sell(self, ctx):
        sell_pe_pb_max = float(self.p.sell_pe_pb_max or 0.0)
        sell_below_ma = (self.p.sell_below_ma or "none").lower()

        if sell_pe_pb_max <= 0 and sell_below_ma == "none":
            return  # 永久持有

        positions = list(ctx.get_positions().items())
        for sym, pos in positions:
            shares = pos.shares if hasattr(pos, "shares") else pos.get("shares", 0)
            if shares <= 0:
                continue

            # ---- 估值退出 ----
            if sell_pe_pb_max > 0:
                pe = valuation.get_pe(ctx, sym)
                pb = valuation.get_pb(ctx, sym)
                if pe is not None and pb is not None and (pe * pb) > sell_pe_pb_max:
                    ctx.order_shares(sym, -shares)
                    ctx.remove_target(sym)
                    ctx.log_exec(
                        "sell_signal",
                        sym,
                        shares=shares,
                        price=0.0,
                        note=f"pe*pb={pe * pb:.2f}>{sell_pe_pb_max}",
                    )
                    continue

            # ---- 月线 MA 退出 ----
            if sell_below_ma in ("ma10", "ma20", "ma30"):
                ma_val = ctx.get_indicator(sell_below_ma, sym, period="monthly")
                price = ctx.get_price(sym, period="monthly") or ctx.get_price(sym)
                close = price.get("close") if price else None
                if ma_val is not None and close is not None and close < ma_val:
                    ctx.order_shares(sym, -shares)
                    ctx.remove_target(sym)
                    ctx.log_exec(
                        "sell_signal",
                        sym,
                        shares=shares,
                        price=float(close),
                        note=f"close={close:.2f}<{sell_below_ma}={ma_val:.2f}",
                    )
