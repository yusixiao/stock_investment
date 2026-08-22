import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import BacktestResult from '../BacktestResult';
import type { BacktestTask } from '../BacktestAnalysis';

const result = {
  totalReturn: 0.1,
  annualizedReturn: 0.1,
  maxDrawdown: 0.02,
  sharpeRatio: 1,
  winRate: 0.5,
  totalTrades: 1,
  profitFactor: 1.2,
  avgWin: 0.1,
  avgLoss: -0.05,
  equityCurve: [],
  trades: [],
  rawBuys: [],
  endPrices: {},
};

function makeTask(status: BacktestTask['status']): BacktestTask {
  return {
    taskId: 'task-1',
    status,
    mode: 'single',
    strategyName: 'Test',
    symbol: '000001.SZ',
    market: 'A',
    period: 'd',
    startDate: '2026-01-01',
    endDate: '2026-01-02',
    capital: 10000,
    commission: 0,
    createdAt: '2026-01-02',
    result,
  };
}

describe('BacktestResult', () => {
  it('does not offer account binding for a completed backtest', () => {
    const task = { ...makeTask('completed'), executionStatus: 'active' as const };
    render(<BacktestResult task={task} />);

    expect(screen.queryByRole('button', { name: /绑定账户/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /解除绑定/ })).not.toBeInTheDocument();
    expect(screen.queryByText('已绑定策略账户')).not.toBeInTheDocument();
  });

  it.each(['pending', 'running', 'failed'] as const)(
    'does not show the bind action for %s tasks',
    (status) => {
      render(<BacktestResult task={makeTask(status)} />);

      expect(screen.queryByRole('button', { name: /绑定账户/ })).not.toBeInTheDocument();
    },
  );
});
