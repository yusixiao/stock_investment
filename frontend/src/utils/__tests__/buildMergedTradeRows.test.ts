import { describe, it, expect } from 'vitest';
import { buildMergedTradeRows } from '../buildMergedTradeRows';
import type { BuyRecord, TradeRecord } from '../../components/backtest/BacktestAnalysis';

describe('buildMergedTradeRows', () => {
  it('空输入返回空数组', () => {
    expect(buildMergedTradeRows([], [])).toEqual([]);
  });

  it('只有 rawBuys 时全部输出为买入行', () => {
    const buys: BuyRecord[] = [
      { date: '2024-01-05', symbol: '600000', price: 10.5, shares: 100 },
      { date: '2024-02-10', symbol: '600000', price: 11.0, shares: 200 },
    ];
    const rows = buildMergedTradeRows(buys, []);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      symbol: '600000',
      side: 'buy',
      date: '2024-01-05',
      price: 10.5,
      shares: 100,
      pnl: null,
      pnlPct: null,
      holdDays: null,
    });
    expect(rows[1].date).toBe('2024-02-10');
  });

  it('单笔 round-trip 卖出生成一行卖,带 pnl/收益率/持仓天数', () => {
    const buys: BuyRecord[] = [
      { date: '2024-01-05', symbol: '600000', price: 10, shares: 100 },
    ];
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-05',
        exitDate: '2024-03-05',
        symbol: '600000',
        direction: 'long',
        entryPrice: 10,
        exitPrice: 12,
        quantity: 100,
        pnl: 200,
        pnlPct: 0.2,
        holdDays: 60,
      },
    ];
    const rows = buildMergedTradeRows(buys, trades);
    expect(rows).toHaveLength(2);
    const sell = rows.find((r) => r.side === 'sell')!;
    expect(sell).toMatchObject({
      symbol: '600000',
      side: 'sell',
      date: '2024-03-05',
      price: 12,
      shares: 100,
      pnl: 200,
      pnlPct: 0.2,
      holdDays: 60,
    });
  });

  it('FIFO 拆分:同一 sell 事件多 round-trip 聚合成一行', () => {
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-01', exitDate: '2024-06-01', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 15, quantity: 100,
        pnl: 500, pnlPct: 0.5, holdDays: 152,
      },
      {
        entryDate: '2024-02-01', exitDate: '2024-06-01', symbol: '600000',
        direction: 'long', entryPrice: 12, exitPrice: 15, quantity: 200,
        pnl: 600, pnlPct: 0.25, holdDays: 121,
      },
    ];
    const rows = buildMergedTradeRows([], trades);
    // 同 symbol+exitDate 聚合成 1 行
    const sells = rows.filter((r) => r.side === 'sell');
    expect(sells).toHaveLength(1);
    const s = sells[0];
    expect(s.shares).toBe(300);
    expect(s.pnl).toBe(1100);
    // pnlPct = total_pnl / total_cost = 1100 / (10*100 + 12*200) = 1100 / 3400
    expect(s.pnlPct).toBeCloseTo(1100 / 3400, 6);
    // 持仓天数按股数加权:(152*100 + 121*200) / 300
    expect(s.holdDays).toBeCloseTo((152 * 100 + 121 * 200) / 300, 4);
    expect(s.price).toBe(15);
  });

  it('不同 symbol 或不同 exitDate 不聚合', () => {
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-01', exitDate: '2024-06-01', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 15, quantity: 100,
        pnl: 500, pnlPct: 0.5, holdDays: 100,
      },
      {
        entryDate: '2024-01-01', exitDate: '2024-07-01', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 16, quantity: 100,
        pnl: 600, pnlPct: 0.6, holdDays: 130,
      },
      {
        entryDate: '2024-01-01', exitDate: '2024-06-01', symbol: '600001',
        direction: 'long', entryPrice: 5, exitPrice: 7, quantity: 200,
        pnl: 400, pnlPct: 0.4, holdDays: 100,
      },
    ];
    const sells = buildMergedTradeRows([], trades).filter((r) => r.side === 'sell');
    expect(sells).toHaveLength(3);
  });

  it('按日期升序排序,同日期 buy 优先于 sell', () => {
    const buys: BuyRecord[] = [
      { date: '2024-03-01', symbol: '600000', price: 10, shares: 100 },
      { date: '2024-01-01', symbol: '600000', price: 10, shares: 100 },
    ];
    const trades: TradeRecord[] = [
      {
        entryDate: '2024-01-01', exitDate: '2024-03-01', symbol: '600000',
        direction: 'long', entryPrice: 10, exitPrice: 12, quantity: 100,
        pnl: 200, pnlPct: 0.2, holdDays: 60,
      },
    ];
    const rows = buildMergedTradeRows(buys, trades);
    expect(rows.map((r) => `${r.date}-${r.side}`)).toEqual([
      '2024-01-01-buy',
      '2024-03-01-buy',
      '2024-03-01-sell',
    ]);
  });
});
