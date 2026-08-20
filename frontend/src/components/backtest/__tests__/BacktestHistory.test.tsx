import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestHistory from '../BacktestHistory';

const { listTasks } = vi.hoisted(() => ({ listTasks: vi.fn() }));

vi.mock('../../../api/backtestEngine', async () => {
  const actual = await vi.importActual<typeof import('../../../api/backtestEngine')>(
    '../../../api/backtestEngine',
  );
  return { ...actual, backtestEngineApi: { ...actual.backtestEngineApi, listTasks } };
});

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
});
