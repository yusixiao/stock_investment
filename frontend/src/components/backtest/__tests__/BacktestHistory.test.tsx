import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestHistory from '../BacktestHistory';

const { listTasks } = vi.hoisted(() => ({ listTasks: vi.fn() }));
const { getAccounts, bindStrategy, createAccount } = vi.hoisted(() => ({
  getAccounts: vi.fn(),
  bindStrategy: vi.fn(),
  createAccount: vi.fn(),
}));

vi.mock('../../../api/backtestEngine', async () => {
  const actual = await vi.importActual<typeof import('../../../api/backtestEngine')>(
    '../../../api/backtestEngine',
  );
  return { ...actual, backtestEngineApi: { ...actual.backtestEngineApi, listTasks } };
});

vi.mock('../../../api/portfolio', () => ({
  portfolioApi: { getAccounts, bindStrategy, createAccount },
}));

const tasks = [
  {
    task_id: 'inactive-task',
    status: 'success',
    task_type: 'backtest',
    pipeline_info: { strategy_name: 'Inactive', symbols: ['000001.SZ'] },
    start_date: null,
    end_date: null,
    summary: { total_return: 0.9 },
    created_at: '2026-08-20T10:00:00',
    deleted: false,
    execution_status: 'inactive' as const,
    execution_account_id: null,
  },
  {
    task_id: 'active-task',
    status: 'success',
    task_type: 'backtest',
    pipeline_info: { strategy_name: 'Active', symbols: ['000002.SZ'] },
    start_date: null,
    end_date: null,
    summary: { total_return: -0.1 },
    created_at: '2026-08-19T10:00:00',
    deleted: false,
    execution_status: 'active' as const,
    execution_account_id: 7,
  },
];

function rowIds(): string[] {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.textContent?.includes('inactive-task') ? 'inactive-task' : 'active-task');
}

describe('BacktestHistory execution ordering', () => {
  beforeEach(() => {
    listTasks.mockResolvedValue(tasks);
  });

  it('keeps active tasks first for default, ascending, and descending return sorting', async () => {
    render(<BacktestHistory />);

    expect(await screen.findByText('执行中')).toBeInTheDocument();
    expect(rowIds()).toEqual(['active-task', 'inactive-task']);

    const sortButton = screen.getByRole('button', { name: /总收益率/ });
    fireEvent.click(sortButton);
    expect(rowIds()).toEqual(['active-task', 'inactive-task']);
    fireEvent.click(sortButton);
    expect(rowIds()).toEqual(['active-task', 'inactive-task']);
  });

  it('binds a successful history task to an existing account', async () => {
    getAccounts.mockResolvedValue({ accounts: [{ id: 7 }] });
    bindStrategy.mockResolvedValue({ id: 7, strategy_task_id: 'inactive-task' });

    render(<BacktestHistory />);
    await screen.findByText('执行中');
    fireEvent.click(screen.getAllByRole('button', { name: '绑定账户' })[1]);

    expect(await screen.findByText('绑定账户')).toBeInTheDocument();
    expect(bindStrategy).toHaveBeenCalledWith(7, 'inactive-task');
    expect(createAccount).not.toHaveBeenCalled();
  });
});
