import type { BuyRecord, TradeRecord } from '../components/backtest/BacktestAnalysis';

/**
 * 持仓汇总行(per-symbol)。
 *
 * 已清仓股票 shares=0、avgCost=0、unrealizedPnl=0,但仍出现在表格里。
 * currentPrice 为 null 表示后端没传该 symbol 的结束日收盘价。
 */
export interface PositionSummaryRow {
  symbol: string;
  shares: number;            // 当前持仓数 = sum(buys) - sum(sold)
  avgCost: number;           // 持仓加权平均成本(剩余成本 / 剩余股数);清仓 = 0
  currentPrice: number | null;
  realizedPnl: number;       // 已实现 = round-trip pnl 之和
  unrealizedPnl: number;     // 未实现 = (currentPrice - avgCost) * shares
  totalPnl: number;          // 总盈亏 = 已实现 + 未实现
  totalReturn: number;       // 总收益率 = totalPnl / 总买入成本
}

export function buildPositionSummary(
  rawBuys: BuyRecord[],
  trades: TradeRecord[],
  endPrices: Record<string, number>,
): PositionSummaryRow[] {
  // 按 symbol 聚合买入与卖出
  const agg = new Map<
    string,
    {
      buyShares: number;
      buyCost: number;
      soldShares: number;
      soldCost: number;     // 已卖出对应的成本基础(round-trip.entryPrice * quantity)
      realizedPnl: number;
    }
  >();

  const ensure = (sym: string) => {
    let a = agg.get(sym);
    if (!a) {
      a = { buyShares: 0, buyCost: 0, soldShares: 0, soldCost: 0, realizedPnl: 0 };
      agg.set(sym, a);
    }
    return a;
  };

  for (const b of rawBuys) {
    const a = ensure(b.symbol);
    a.buyShares += b.shares;
    a.buyCost += b.price * b.shares;
  }
  for (const t of trades) {
    const a = ensure(t.symbol);
    a.soldShares += t.quantity;
    a.soldCost += t.entryPrice * t.quantity;
    a.realizedPnl += t.pnl;
  }

  const rows: PositionSummaryRow[] = [];
  for (const [symbol, a] of agg) {
    const shares = a.buyShares - a.soldShares;
    const remainingCost = a.buyCost - a.soldCost;
    const avgCost = shares > 0 ? remainingCost / shares : 0;
    const currentPrice = endPrices[symbol] != null ? endPrices[symbol] : null;
    const unrealizedPnl =
      shares > 0 && currentPrice != null ? (currentPrice - avgCost) * shares : 0;
    const totalPnl = a.realizedPnl + unrealizedPnl;
    const totalReturn = a.buyCost > 0 ? totalPnl / a.buyCost : 0;
    rows.push({
      symbol,
      shares,
      avgCost,
      currentPrice,
      realizedPnl: a.realizedPnl,
      unrealizedPnl,
      totalPnl,
      totalReturn,
    });
  }

  // 仍持仓的排前(更关注),其次按 symbol
  rows.sort((a, b) => {
    if ((a.shares > 0) !== (b.shares > 0)) return a.shares > 0 ? -1 : 1;
    return a.symbol < b.symbol ? -1 : a.symbol > b.symbol ? 1 : 0;
  });

  return rows;
}
