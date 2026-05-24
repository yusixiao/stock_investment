import * as XLSX from 'xlsx';
import type { MergedTradeRow } from './buildMergedTradeRows';

/**
 * 导出合并后的买卖明细为 .xlsx。买入行的盈亏/收益率/持仓天数留空(显示 '-')。
 * 表头与 BacktestResult 合并表格一致。
 */
export function exportTradesToXlsx(
  rows: MergedTradeRow[],
  filename: string,
): void {
  if (!rows || rows.length === 0) return;

  const data = rows.map((r) => ({
    股票: r.symbol,
    方向: r.side === 'buy' ? '买' : '卖',
    日期: r.date,
    价格: Number(r.price.toFixed(4)),
    数量: r.shares,
    盈亏: r.pnl == null ? '-' : Number(r.pnl.toFixed(2)),
    '收益率(%)': r.pnlPct == null ? '-' : Number((r.pnlPct * 100).toFixed(2)),
    持仓天数: r.holdDays == null ? '-' : Number(r.holdDays.toFixed(1)),
  }));

  const ws = XLSX.utils.json_to_sheet(data);
  ws['!cols'] = [
    { wch: 12 }, // 股票
    { wch: 6 },  // 方向
    { wch: 12 }, // 日期
    { wch: 10 }, // 价格
    { wch: 10 }, // 数量
    { wch: 12 }, // 盈亏
    { wch: 10 }, // 收益率
    { wch: 10 }, // 持仓天数
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '交易明细');
  XLSX.writeFile(wb, filename);
}

/** 用任务信息生成默认文件名:策略名_标的_起止_交易明细.xlsx */
export function buildTradesFilename(opts: {
  strategyName?: string;
  symbol?: string | null;
  market?: string | null;
  startDate?: string;
  endDate?: string;
}): string {
  const safe = (s: string | null | undefined) =>
    (s || '').replace(/[\\/:*?"<>|]/g, '_').trim();
  const parts = [
    safe(opts.strategyName) || '回测',
    safe(opts.symbol) || safe(opts.market) || '',
    safe(opts.startDate),
    safe(opts.endDate),
    '交易明细',
  ].filter(Boolean);
  return `${parts.join('_')}.xlsx`;
}
