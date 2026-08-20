import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestHistory from '../BacktestHistory';

const { listTasks } = vi.hoisted(() => ({ listTasks: vi.fn() }));
const { getAccounts, getSnapshot, bindStrategy, createAccount } = vi.hoisted(() => ({
  getAccounts: vi.fn(),
  getSnapshot: vi.fn(),
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
  portfolioApi: { getAccounts, getSnapshot, bindStrategy, createAccount },
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

function bindButtonFor(taskId: string): HTMLElement {
  const row = screen.getByText(taskId).closest('tr');
  if (!row) throw new Error(`row not found: ${taskId}`);
  return within(row).getByRole('button', { name: '绑定账户' });
}

describe('BacktestHistory execution ordering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listTasks.mockResolvedValue(tasks);
    getAccounts.mockResolvedValue({ accounts: [] });
    getSnapshot.mockResolvedValue({ accounts: [{ positions: [] }] });
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
    getSnapshot.mockResolvedValue({ accounts: [{ positions: [] }] });
    bindStrategy.mockResolvedValue({ id: 7, strategy_task_id: 'inactive-task' });

    render(<BacktestHistory />);
    await screen.findByText('执行中');
    fireEvent.click(bindButtonFor('inactive-task'));

    expect(await screen.findByText('绑定账户')).toBeInTheDocument();
    expect(bindStrategy).toHaveBeenCalledWith(7, 'inactive-task');
    expect(createAccount).not.toHaveBeenCalled();
  });

  it('filters bound and occupied accounts before binding', async () => {
    getAccounts.mockResolvedValue({ accounts: [
      { id: 5, strategyTaskId: 'another-task' },
      { id: 6 },
      { id: 7 },
    ] });
    getSnapshot.mockImplementation(({ accountId }: { accountId: number }) => Promise.resolve({
      accounts: [{ positions: accountId === 6 ? [{ quantity: 2 }] : [] }],
    }));
    bindStrategy.mockResolvedValue({ id: 7, strategy_task_id: 'inactive-task' });

    render(<BacktestHistory />);
    await screen.findByText('执行中');
    fireEvent.click(bindButtonFor('inactive-task'));

    expect(await screen.findByText('绑定账户')).toBeInTheDocument();
    expect(bindStrategy).toHaveBeenCalledWith(7, 'inactive-task');
    expect(bindStrategy).not.toHaveBeenCalledWith(5, expect.anything());
    expect(bindStrategy).not.toHaveBeenCalledWith(6, expect.anything());
  });

  it('does not show bind actions for active, failed, or running tasks', async () => {
    listTasks.mockResolvedValue([
      ...tasks,
      { ...tasks[0], task_id: 'failed-task', status: 'failed' },
      { ...tasks[0], task_id: 'running-task', status: 'running' },
    ]);

    render(<BacktestHistory />);

    await screen.findByText('执行中');
    expect(screen.getAllByRole('button', { name: '绑定账户' })).toHaveLength(1);
  });

  it('removes the bind action after refresh marks the task active', async () => {
    listTasks
      .mockResolvedValueOnce(tasks)
      .mockResolvedValueOnce(tasks.map((task) => (
        task.task_id === 'inactive-task' ? { ...task, execution_status: 'active', execution_account_id: 7 } : task
      )));
    getAccounts.mockResolvedValue({ accounts: [{ id: 7 }] });
    getSnapshot.mockResolvedValue({ accounts: [{ positions: [] }] });
    bindStrategy.mockResolvedValue({ id: 7, strategy_task_id: 'inactive-task' });

    render(<BacktestHistory />);
    await screen.findByText('执行中');
    fireEvent.click(bindButtonFor('inactive-task'));

    expect(await screen.findByText('执行中')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '绑定账户' })).not.toBeInTheDocument();
  });

  it('shows a visible error when binding fails', async () => {
    getAccounts.mockResolvedValue({ accounts: [{ id: 7 }] });
    getSnapshot.mockResolvedValue({ accounts: [{ positions: [] }] });
    bindStrategy.mockRejectedValue(new Error('task is already active'));

    render(<BacktestHistory />);
    await screen.findAllByText('执行中');
    fireEvent.click(bindButtonFor('inactive-task'));

    expect(await screen.findByRole('alert')).toHaveTextContent('task is already active');
  });
});
