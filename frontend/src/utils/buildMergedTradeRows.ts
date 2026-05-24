import type { BuyRecord, TradeRecord } from '../components/backtest/BacktestAnalysis';

/**
 * 合并表格行:买入行来自 raw_trades 的 buy 事件;卖出行由 round-trip(已 FIFO 拆分)
 * 按 (symbol, exitDate) 聚合为一行 — 同一卖出事件 pnl 求和、shares 求和、
 * pnlPct 用总 pnl/总成本、持仓天数按 shares 加权平均。
 */
export interface MergedTradeRow {
  symbol: string;
  side: 'buy' | 'sell';
  date: string;
  price: number;
  shares: number;
  // 仅 sell 行有值,buy 行为 null(展示时用 '-')
  pnl: number | null;
  pnlPct: number | null;
  holdDays: number | null;
}

export function buildMergedTradeRows(
  rawBuys: BuyRecord[],
  trades: TradeRecord[],
): MergedTradeRow[] {
  const rows: MergedTradeRow[] = [];

  // 买入行:直接展开
  for (const b of rawBuys) {
    rows.push({
      symbol: b.symbol,
      side: 'buy',
      date: b.date,
      price: b.price,
      shares: b.shares,
      pnl: null,
      pnlPct: null,
      holdDays: null,
    });
  }

  // 卖出行:按 (symbol, exitDate) 聚合
  // 同一 sell 事件可能因 FIFO 配对多笔 buy 拆成多个 round-trip,这里合并回单行
  const sellGroups = new Map<string, TradeRecord[]>();
  for (const t of trades) {
    const key = `${t.symbol}|${t.exitDate}`;
    const arr = sellGroups.get(key);
    if (arr) arr.push(t);
    else sellGroups.set(key, [t]);
  }

  for (const group of sellGroups.values()) {
    const totalShares = group.reduce((s, t) => s + t.quantity, 0);
    const totalPnl = group.reduce((s, t) => s + t.pnl, 0);
    // pnlPct = 总 pnl / 总成本(更准确,避免简单加权 pct 受单价差异扭曲)
    const totalCost = group.reduce((s, t) => s + t.entryPrice * t.quantity, 0);
    const pnlPct = totalCost > 0 ? totalPnl / totalCost : 0;
    // 持仓天数按 shares 加权
    const weightedHold = group.reduce((s, t) => s + t.holdDays * t.quantity, 0);
    const holdDays = totalShares > 0 ? weightedHold / totalShares : 0;
    const first = group[0];
    rows.push({
      symbol: first.symbol,
      side: 'sell',
      date: first.exitDate,
      price: first.exitPrice,
      shares: totalShares,
      pnl: totalPnl,
      pnlPct,
      holdDays,
    });
  }

  // 按日期升序;同日期 buy 排前(更符合直觉:先建仓再清仓)
  rows.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    if (a.side !== b.side) return a.side === 'buy' ? -1 : 1;
    return a.symbol < b.symbol ? -1 : a.symbol > b.symbol ? 1 : 0;
  });

  return rows;
}
