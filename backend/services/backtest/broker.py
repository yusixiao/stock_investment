import logging
from dataclasses import dataclass, field
from services.backtest.portfolio import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class Order:
    symbol: str
    shares: int
    direction: str
    status: str = "pending"


class Broker:
    def __init__(
        self,
        initial_capital: float = 1_000_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.002,
    ):
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.portfolio = Portfolio(initial_capital)
        self.pending_orders: list[Order] = []
        self.all_trades: list[dict] = []

    def submit_order(self, symbol: str, shares: int, direction: str):
        logger.debug(
            "提交订单: symbol=%s, shares=%d, direction=%s", symbol, shares, direction
        )
        self.pending_orders.append(
            Order(symbol=symbol, shares=shares, direction=direction)
        )

    def fill_orders(
        self,
        date: str,
        bars: dict[str, dict],
        prev_closes: dict[str, float],
    ) -> list[dict]:
        trades = []
        remaining = []
        for order in self.pending_orders:
            bar = bars.get(order.symbol)
            if bar is None:
                remaining.append(order)
                continue
            prev_close = prev_closes.get(order.symbol)
            trade = self._try_fill(order, bar, prev_close, date)
            if trade is not None:
                trades.append(trade)
        self.pending_orders = remaining
        self.all_trades.extend(trades)
        return trades

    def _try_fill(
        self, order: Order, bar: dict, prev_close: float | None, date: str
    ) -> dict | None:
        # 停牌/无成交日拒单:BaoStock 派生数据对停牌日填充 OHLC=上一根 close、
        # volume=0,会绕过涨跌停判断("low==high==prev_close" 不是 ±10%)。
        # 为防止此类伪交易日成交,显式拒绝 volume=0 的订单。
        # 兼容老调用方:bar 未提供 volume 字段时不做检查。
        vol = bar.get("volume")
        if vol is not None and vol <= 0:
            logger.debug("订单被拒: %s volume=0 (停牌/无成交)", order.symbol)
            return None

        # 成交价取开盘价和收盘价的中间价，模拟日内均价成交
        mid_price = (bar["open"] + bar["close"]) / 2

        # 涨跌停判断：当日最高=最低=涨停/跌停价，视为一字板无法成交
        if prev_close is not None:
            limit_up = round(prev_close * 1.1, 2)
            limit_down = round(prev_close * 0.9, 2)
            is_limit_up = bar["low"] == bar["high"] == limit_up
            is_limit_down = bar["low"] == bar["high"] == limit_down
            if order.direction == "buy" and is_limit_up:
                logger.debug("订单被拒: %s 涨停无法买入", order.symbol)
                return None
            if order.direction == "sell" and is_limit_down:
                logger.debug("订单被拒: %s 跌停无法卖出", order.symbol)
                return None

        if order.direction == "buy":
            fill_price = mid_price * (1 + self.slippage)
            shares = (order.shares // 100) * 100
            if shares <= 0:
                return None
            commission = max(shares * fill_price * self.commission_rate, 5.0)
            total_cost = shares * fill_price + commission
            if total_cost > self.portfolio.cash:
                # 资金不足:按可用现金能买的最大整百手【部分成交】,而非整单拒绝。
                # 背景:等权满仓策略每次调仓把 100% 权益均摊到 N 只,按信号日收盘价
                # 定股数、次日中间价+滑点成交,累计成本必然略超预算,排序最后一只常
                # 因差一点被整单丢弃 → 近一整个仓位现金空转。改为尽量买,只缩减该只。
                cash = self.portfolio.cash
                # 上界估计:total_cost ≈ shares*fill_price*(1+commission_rate)
                # (大额单佣金取比例项;向下取整到整百手保证不超支)
                affordable = int(cash / (fill_price * (1 + self.commission_rate))) // 100 * 100
                # 佣金 5 元下限可能使上界估计略微超支,逐手回退到严格满足为止
                while affordable > 0:
                    commission = max(affordable * fill_price * self.commission_rate, 5.0)
                    if affordable * fill_price + commission <= cash:
                        break
                    affordable -= 100
                if affordable <= 0:
                    logger.debug(
                        "订单被拒: %s 资金不足,可用%.2f 不足一手 (@%.3f)",
                        order.symbol,
                        cash,
                        fill_price,
                    )
                    return None
                logger.debug(
                    "部分成交: %s 资金不足,目标%d 股缩减至%d 股 (可用%.2f)",
                    order.symbol,
                    shares,
                    affordable,
                    cash,
                )
                shares = affordable
                commission = max(shares * fill_price * self.commission_rate, 5.0)
                total_cost = shares * fill_price + commission
            self.portfolio.buy(order.symbol, shares, fill_price, commission, date)
            logger.debug(
                "成交: date=%s, symbol=%s, buy@%.3f, shares=%d",
                date,
                order.symbol,
                fill_price,
                shares,
            )
            return {
                "date": date,
                "symbol": order.symbol,
                "direction": "buy",
                "price": fill_price,
                "shares": shares,
                "commission": commission,
                "tax": 0.0,
                "amount": shares * fill_price,
            }

        elif order.direction == "sell":
            pos = self.portfolio.get_position(order.symbol)
            if pos is None:
                return None
            # T+1限制：买入当日不能卖出（buy_date必须早于当前date）
            if pos["buy_date"] >= date:
                logger.debug(
                    "订单被拒: %s T+1限制 (买入日%s, 当前%s)",
                    order.symbol,
                    pos["buy_date"],
                    date,
                )
                return None
            sell_shares = min(order.shares, pos["shares"])
            if sell_shares <= 0:
                return None
            fill_price = mid_price * (1 - self.slippage)
            commission = max(sell_shares * fill_price * self.commission_rate, 5.0)
            tax = sell_shares * fill_price * 0.001
            self.portfolio.sell(order.symbol, sell_shares, fill_price, commission, tax)
            logger.debug(
                "成交: date=%s, symbol=%s, sell@%.3f, shares=%d",
                date,
                order.symbol,
                fill_price,
                sell_shares,
            )
            return {
                "date": date,
                "symbol": order.symbol,
                "direction": "sell",
                "price": fill_price,
                "shares": sell_shares,
                "commission": commission,
                "tax": tax,
                "amount": sell_shares * fill_price,
            }

        return None
