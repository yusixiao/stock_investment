import { describe, it, expect } from 'vitest';
import { buildPositionSummary } from '../buildPositionSummary';
import type { BuyRecord, TradeRecord } from '../../components/backtest/BacktestAnalysis';

describe('buildPositionSummary', () => {
  it('空输入返回空数组', () => {
    expect(buildPositionSummary([], [], {})).toEqual([]);
  });

  it('完全清仓:持仓 0,未实现 0,已实现 = round-trip pnl 之和', () => {
    const buys: BuyRecord[] = [
      { date: '2024-01-05', symbol: '600000', price: 10, shares: 100 },
    ];
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-05', exitDate: '2024-03-05', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 12, quantity: 100,
        pnl: 200, pnlPct: 0.2, holdDays: 60,
      },
    ];
    const rows = buildPositionSummary(buys, trades, { '600000': 13 });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      symbol: '600000',
      shares: 0,
      avgCost: 0,        // 已清仓 → 持仓成本 0
      currentPrice: 13,
      realizedPnl: 200,
      unrealizedPnl: 0,  // 持仓 0 → 未实现 0
      totalPnl: 200,
    });
    // 总收益率 = 总盈亏 / 总买入成本(10*100 = 1000)
    expect(rows[0].totalReturn).toBeCloseTo(200 / 1000, 6);
  });

  it('部分持仓:剩余持仓的加权成本 + 未实现盈亏', () => {
    // 买 200 股 @ 10、买 100 股 @ 12,总买入 = 300 股、成本 3200
    // 卖 200 股 @ 15(FIFO 配 200 股 @ 10)→ 已实现 = (15-10)*200 = 1000
    // 剩余 100 股 @ 12,当前价 18 → 未实现 = (18-12)*100 = 600
    const buys: BuyRecord[] = [
      { date: '2024-01-01', symbol: '600000', price: 10, shares: 200 },
      { date: '2024-02-01', symbol: '600000', price: 12, shares: 100 },
    ];
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-01', exitDate: '2024-06-01', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 15, quantity: 200,
        pnl: 1000, pnlPct: 0.5, holdDays: 152,
      },
    ];
    const rows = buildPositionSummary(buys, trades, { '600000': 18 });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      symbol: '600000',
      shares: 100,
      avgCost: 12,
      currentPrice: 18,
      realizedPnl: 1000,
      unrealizedPnl: 600,
      totalPnl: 1600,
    });
    // 总买入成本 = 10*200 + 12*100 = 3200
    expect(rows[0].totalReturn).toBeCloseTo(1600 / 3200, 6);
  });

  it('end_prices 缺失某 symbol 时,持仓中股票当前价为 null,未实现 0', () => {
    const buys: BuyRecord[] = [
      { date: '2024-01-01', symbol: '600000', price: 10, shares: 100 },
    ];
    const rows = buildPositionSummary(buys, [], {});
    expect(rows[0].currentPrice).toBeNull();
    expect(rows[0].unrealizedPnl).toBe(0);
  });

  it('多 symbol 按 symbol 分组', () => {
    const buys: BuyRecord[] = [
      { date: '2024-01-01', symbol: '600000', price: 10, shares: 100 },
      { date: '2024-01-01', symbol: '600001', price: 5, shares: 200 },
    ];
    const rows = buildPositionSummary(buys, [], { '600000': 11, '600001': 6 });
    expect(rows.map((r) => r.symbol).sort()).toEqual(['600000', '600001']);
  });

  it('FIFO 拆分:部分批次卖完 + 部分仍持有', () => {
    // 买 100 @ 10、买 100 @ 20,卖 150(FIFO:100@10 + 50@20)
    // 剩余 50 股 @ 20,当前价 25
    const buys: BuyRecord[] = [
      { date: '2024-01-01', symbol: '600000', price: 10, shares: 100 },
      { date: '2024-02-01', symbol: '600000', price: 20, shares: 100 },
    ];
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-01', exitDate: '2024-06-01', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 22, quantity: 100,
        pnl: 1200, pnlPct: 1.2, holdDays: 152,
      },
      {
        entryDate: '2024-02-01', exitDate: '2024-06-01', symbol: '600000',
        direction: 'long', entryPrice: 20, exitPrice: 22, quantity: 50,
        pnl: 100, pnlPct: 0.1, holdDays: 121,
      },
    ];
    const rows = buildPositionSummary(buys, trades, { '600000': 25 });
    expect(rows[0]).toMatchObject({
      shares: 50,
      avgCost: 20,
      realizedPnl: 1300,
      unrealizedPnl: 250,  // (25-20)*50
      totalPnl: 1550,
    });
  });
});
