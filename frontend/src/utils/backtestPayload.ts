import type { BacktestResultPayload } from '../api/backtestEngine';
import type { BacktestResultData } from '../components/backtest/BacktestAnalysis';

// 将后端 BacktestResultPayload 映射为前端 BacktestResultData。
// BacktestConfig(新跑任务)与 BacktestHistory(查看历史)共用,避免字段映射散落多处
export function mapPayloadToResultData(
  payload: BacktestResultPayload,
): BacktestResultData | null {
  if (!payload?.metrics) return null;
  return {
    totalReturn: payload.metrics.total_return,
    annualizedReturn: payload.metrics.annualized_return,
    maxDrawdown: payload.metrics.max_drawdown,
    sharpeRatio: payload.metrics.sharpe_ratio,
    winRate: payload.metrics.win_rate,
    totalTrades: payload.metrics.total_trades,
    profitFactor: payload.metrics.profit_factor,
    avgWin: payload.metrics.avg_win,
    avgLoss: payload.metrics.avg_loss,
    equityCurve: (payload.equity_curve || []).map((e) => ({
      date: e.date,
      value: e.value ?? e.total_value ?? 0,
    })),
    trades: (payload.trades || []).map((t) => ({
      entryDate: t.entry_date,
      exitDate: t.exit_date,
      symbol: t.symbol,
      direction: t.direction as 'long' | 'short',
      entryPrice: t.entry_price,
      exitPrice: t.exit_price,
      quantity: t.shares,
      pnl: t.pnl,
      pnlPct: t.pnl_pct,
      holdDays: t.hold_days,
    })),
    rawBuys: (payload.raw_trades || [])
      .filter((t) => t.direction === 'buy')
      .map((t) => ({
        date: t.date,
        symbol: t.symbol,
        price: t.price,
        shares: t.shares,
      })),
  };
}
