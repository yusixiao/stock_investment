import * as XLSX from 'xlsx';
import type { TradeRecord } from '../components/backtest/BacktestAnalysis';

/**
 * 把交易明细导出成 .xlsx 文件,通过浏览器下载对话框让用户选保存路径。
 *
 * 表头与 BacktestResult 表格一致(中文)。
 */
export function exportTradesToXlsx(
  trades: TradeRecord[],
  filename: string,
): void {
  if (!trades || trades.length === 0) return;

  // 行数据:中文表头,数值用 Number 保留可计算性,百分比/方向显式转中文
  const rows = trades.map((t) => ({
    股票: t.symbol,
    方向: t.direction === 'long' ? '做多' : '做空',
    买入日期: t.entryDate,
    卖出日期: t.exitDate,
    买入价: Number(t.entryPrice.toFixed(4)),
    卖出价: Number(t.exitPrice.toFixed(4)),
    数量: t.quantity,
    盈亏: Number(t.pnl.toFixed(2)),
    '收益率(%)': Number((t.pnlPct * 100).toFixed(2)),
    持仓天数: t.holdDays,
  }));

  const ws = XLSX.utils.json_to_sheet(rows);
  // 列宽美化
  ws['!cols'] = [
    { wch: 12 }, // 股票
    { wch: 6 },  // 方向
    { wch: 12 }, // 买入日期
    { wch: 12 }, // 卖出日期
    { wch: 10 }, // 买入价
    { wch: 10 }, // 卖出价
    { wch: 10 }, // 数量
    { wch: 12 }, // 盈亏
    { wch: 10 }, // 收益率
    { wch: 10 }, // 持仓天数
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '交易明细');
  // writeFile 内部会触发浏览器下载对话框,用户在对话框选保存路径
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
