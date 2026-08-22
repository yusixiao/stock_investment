import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestHistory from '../BacktestHistory';
import BacktestDetail from '../BacktestDetail';

const { listTasks, getResult, deleteTask } = vi.hoisted(() => ({
  listTasks: vi.fn(),
  getResult: vi.fn(),
  deleteTask: vi.fn(),
}));
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
  return { ...actual, backtestEngineApi: { ...actual.backtestEngineApi, listTasks, getResult, deleteTask } };
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

  it('labels monitor-triggered tasks in history', async () => {
    listTasks.mockResolvedValue([
      {
        ...tasks[0],
        task_id: 'monitor-task',
        task_type: 'monitor',
        pipeline_info: {
          strategy_name: '监控策略',
          trigger_source: 'monitor',
          symbols: ['000001.SZ'],
        },
      },
    ]);

    render(<BacktestHistory />);

    const row = await screen.findByText('monitor-task');
    expect(within(row.closest('tr') as HTMLElement).getByText('监控触发')).toBeInTheDocument();
  });

  it('uses the monitor strategy name when the task name field is absent', async () => {
    listTasks.mockResolvedValue([
      {
        ...tasks[0],
        task_id: 'monitor-name-fallback',
        task_type: 'monitor',
        pipeline_info: {
          strategy_class: 'LynchSlowGrowersStrategy',
          monitor_name: '彼得林奇缓慢增长策略',
          trigger_source: 'monitor',
        },
      },
    ]);

    render(<BacktestHistory />);

    expect(await screen.findByText('彼得林奇缓慢增长策略')).toBeInTheDocument();
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

  it('uses consistent shared variants for bind and delete actions', async () => {
    render(<BacktestHistory />);

    await screen.findByText('执行中');

    const inactiveRow = screen.getByText('inactive-task').closest('tr');
    if (!inactiveRow) throw new Error('inactive task row not found');

    expect(within(inactiveRow).getByRole('button', { name: '绑定账户' })).toHaveAttribute(
      'data-variant',
      'outline',
    );
    expect(within(inactiveRow).getByRole('button', { name: /删除/ })).toHaveAttribute(
      'data-variant',
      'danger-subtle',
    );
  });

  it('asks for confirmation before deleting a history task', async () => {
    render(<BacktestHistory />);

    await screen.findByText('执行中');
    const inactiveRow = screen.getByText('inactive-task').closest('tr');
    if (!inactiveRow) throw new Error('inactive task row not found');

    fireEvent.click(within(inactiveRow).getByRole('button', { name: '删除' }));

    expect(screen.getByText(/确认删除这条回测记录吗/)).toBeInTheDocument();
    expect(deleteTask).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    expect(deleteTask).toHaveBeenCalledWith('inactive-task');
  });

  it('centers history actions and aligns toolbar text metrics', async () => {
    render(<BacktestHistory />);

    await screen.findByText('执行中');

    const toolbarLabel = screen.getByText('显示已删除').closest('label');
    const refreshButton = screen.getByRole('button', { name: '刷新' });
    const inactiveRow = screen.getByText('inactive-task').closest('tr');
    const actionGroup = inactiveRow?.querySelector('td:last-child > div');

    expect(toolbarLabel).toHaveClass('text-sm', 'font-medium', 'leading-5');
    expect(refreshButton).toHaveClass('text-sm', 'font-medium', 'leading-5');
    expect(actionGroup).toHaveClass('justify-end');
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

  it('opens monitor history with its metadata and radar hits', async () => {
    const monitorTask = {
      task_id: 'monitor-task',
      status: 'success',
      task_type: 'monitor',
      pipeline_info: {
        strategy_name: '监控策略',
        params: { frequency: 'weekly' },
        symbols: ['000001.SZ'],
        market: 'A',
      },
      start_date: '2026-02-20',
      end_date: '2026-08-21',
      summary: {},
      created_at: '2026-08-21T10:00:00',
      deleted: false,
      execution_status: 'inactive' as const,
      execution_account_id: null,
    };
    const radarPayload = {
      hits: [{
        symbol: '000001.SZ',
        name: '平安银行',
        current_price: 12.3,
        signal_close: 12,
        change_pct_since_signal: 0.025,
        last_match_date: '2026-08-20',
        match_count: 2,
        factors: { score: 1 },
      }],
      total_scanned: 1,
      lookback_used: 'custom' as const,
      date_range: { start: '2026-02-20', end: '2026-08-21' },
      data_latest_date: '2026-08-21',
      strategy_class: 'MonitorStrategy',
      strategy_name: '监控策略',
      frequency: 'weekly',
    };
    listTasks.mockResolvedValue([monitorTask]);
    getResult.mockResolvedValue({
      task_id: 'monitor-task',
      status: 'success',
      task_type: 'monitor',
      pipeline_info: monitorTask.pipeline_info,
      start_date: monitorTask.start_date,
      end_date: monitorTask.end_date,
      result: radarPayload,
      created_at: monitorTask.created_at,
      execution_status: 'inactive',
      execution_account_id: null,
    });
    const selected = vi.fn();

    const { unmount } = render(<BacktestHistory onSelect={selected} />);
    fireEvent.click(await screen.findByText('监控策略'));

    const task = await waitFor(() => {
      const selectedTask = selected.mock.calls[0]?.[0];
      expect(selectedTask).toBeDefined();
      return selectedTask;
    });
    expect(task).toMatchObject({
      taskType: 'monitor',
      strategyName: '监控策略',
      startDate: '2026-02-20',
      endDate: '2026-08-21',
      radarPayload,
    });

    unmount();
    render(<BacktestDetail task={task} onBack={vi.fn()} />);
    expect(screen.getByText('监控策略')).toBeInTheDocument();
    expect(screen.getByText('监控触发')).toBeInTheDocument();
    expect(screen.getByText('2026-02-20 ~ 2026-08-21')).toBeInTheDocument();
    expect(screen.getAllByText('000001.SZ')).toHaveLength(2);
  });
});
