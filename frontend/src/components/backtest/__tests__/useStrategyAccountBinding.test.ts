import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TaskListItem } from '../../../api/backtestEngine';
import { useStrategyAccountBinding } from '../useStrategyAccountBinding';

const portfolioApi = vi.hoisted(() => ({
  getAccounts: vi.fn(),
  getSnapshot: vi.fn(),
  bindStrategy: vi.fn(),
  createAccount: vi.fn(),
}));

vi.mock('../../../api/portfolio', () => ({ portfolioApi }));

const task: TaskListItem = {
  task_id: 'task-1',
  status: 'success',
  task_type: 'backtest',
  pipeline_info: { strategy_name: '价值策略', market: 'A' },
  start_date: null,
  end_date: null,
  created_at: '2026-08-22T10:00:00',
  deleted: false,
  execution_status: 'inactive',
  execution_account_id: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

describe('useStrategyAccountBinding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    portfolioApi.getAccounts.mockResolvedValue({ accounts: [] });
    portfolioApi.getSnapshot.mockResolvedValue({ accounts: [{ positions: [] }] });
    portfolioApi.bindStrategy.mockResolvedValue({ id: 2 });
    portfolioApi.createAccount.mockResolvedValue({ id: 3 });
  });

  it('filters bound accounts and binds the first account without holdings', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    portfolioApi.getAccounts.mockResolvedValue({
      accounts: [
        { id: 1, strategyTaskId: 'another-task' },
        { id: 2 },
        { id: 3 },
      ],
    });
    portfolioApi.getSnapshot.mockImplementation(({ accountId }: { accountId: number }) => Promise.resolve({
      accounts: [{ positions: accountId === 2 ? [{ quantity: 1 }] : [] }],
    }));

    const { result } = renderHook(() => useStrategyAccountBinding({ refresh }));
    await act(async () => {
      await result.current.bindTask(task);
    });

    expect(portfolioApi.getSnapshot).toHaveBeenCalledWith({ accountId: 2 });
    expect(portfolioApi.getSnapshot).toHaveBeenCalledWith({ accountId: 3 });
    expect(portfolioApi.getSnapshot).not.toHaveBeenCalledWith({ accountId: 1 });
    expect(portfolioApi.bindStrategy).toHaveBeenCalledWith(3, 'task-1');
    expect(refresh).toHaveBeenCalledOnce();
    expect(result.current.bindingId).toBeNull();
  });

  it('creates a market-specific account when no eligible account exists', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    portfolioApi.getAccounts.mockResolvedValue({ accounts: [{ id: 1 }] });
    portfolioApi.getSnapshot.mockResolvedValue({ accounts: [{ positions: [{ quantity: 2 }] }] });

    const { result } = renderHook(() => useStrategyAccountBinding({ refresh }));
    await act(async () => {
      await result.current.bindTask({
        ...task,
        pipeline_info: { strategy_name: '美股策略', market: 'US' },
      });
    });

    expect(portfolioApi.createAccount).toHaveBeenCalledWith({
      name: '美股策略策略账户',
      market: 'us',
      baseCurrency: 'USD',
      strategyTaskId: 'task-1',
    });
    expect(portfolioApi.bindStrategy).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('exposes parsed API errors and does not refresh after a failed bind', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    portfolioApi.getAccounts.mockRejectedValue(new Error('account lookup failed'));
    const { result } = renderHook(() => useStrategyAccountBinding({ refresh }));

    await act(async () => {
      await result.current.bindTask(task);
    });

    await waitFor(() => expect(result.current.bindingError).toMatchObject({
      title: '请求失败',
      message: 'account lookup failed',
    }));
    expect(refresh).not.toHaveBeenCalled();
    expect(result.current.bindingId).toBeNull();
  });

  it('keeps the latest binding state when an older request finishes later', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const firstAccounts = deferred<{ accounts: [] }>();
    const secondAccounts = deferred<{ accounts: [] }>();
    portfolioApi.getAccounts
      .mockReturnValueOnce(firstAccounts.promise)
      .mockReturnValueOnce(secondAccounts.promise);
    const { result } = renderHook(() => useStrategyAccountBinding({ refresh }));
    const firstTask = { ...task, task_id: 'task-a' };
    const secondTask = { ...task, task_id: 'task-b' };

    let firstRequest!: Promise<void>;
    let secondRequest!: Promise<void>;
    await act(async () => {
      firstRequest = result.current.bindTask(firstTask);
      secondRequest = result.current.bindTask(secondTask);
      await Promise.resolve();
    });

    await act(async () => {
      firstAccounts.reject(new Error('old request failed'));
      await firstRequest;
    });
    expect(result.current.bindingId).toBe('task-b');
    expect(result.current.bindingError).toBeNull();

    await act(async () => {
      secondAccounts.reject(new Error('latest request failed'));
      await secondRequest;
    });
    expect(result.current.bindingId).toBeNull();
    expect(result.current.bindingError).toMatchObject({ message: 'latest request failed' });
  });

  it('does not let an older successful request clear a newer binding', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const firstAccounts = deferred<{ accounts: [{ id: number }] }>();
    const secondAccounts = deferred<{ accounts: [] }>();
    const firstBind = deferred<{ id: number }>();
    portfolioApi.getAccounts
      .mockReturnValueOnce(firstAccounts.promise)
      .mockReturnValueOnce(secondAccounts.promise);
    portfolioApi.bindStrategy.mockReturnValueOnce(firstBind.promise);
    const { result } = renderHook(() => useStrategyAccountBinding({ refresh }));
    const firstTask = { ...task, task_id: 'task-a' };
    const secondTask = { ...task, task_id: 'task-b' };

    let firstRequest!: Promise<void>;
    let secondRequest!: Promise<void>;
    await act(async () => {
      firstRequest = result.current.bindTask(firstTask);
      secondRequest = result.current.bindTask(secondTask);
      await Promise.resolve();
    });

    await act(async () => {
      firstAccounts.resolve({ accounts: [{ id: 1 }] });
      await Promise.resolve();
    });
    await waitFor(() => expect(portfolioApi.bindStrategy).toHaveBeenCalledWith(1, 'task-a'));

    await act(async () => {
      firstBind.resolve({ id: 1 });
      await firstRequest;
    });
    expect(result.current.bindingId).toBe('task-b');
    expect(result.current.bindingError).toBeNull();

    await act(async () => {
      secondAccounts.reject(new Error('latest request failed'));
      await secondRequest;
    });
  });

  it('refreshes only for the latest successful binding request', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const firstAccounts = deferred<{ accounts: [{ id: number }] }>();
    const secondAccounts = deferred<{ accounts: [] }>();
    const firstBind = deferred<{ id: number }>();
    portfolioApi.getAccounts
      .mockReturnValueOnce(firstAccounts.promise)
      .mockReturnValueOnce(secondAccounts.promise);
    portfolioApi.bindStrategy.mockReturnValueOnce(firstBind.promise);

    const { result } = renderHook(() => useStrategyAccountBinding({ refresh }));
    let firstRequest!: Promise<void>;
    let secondRequest!: Promise<void>;
    await act(async () => {
      firstRequest = result.current.bindTask({ ...task, task_id: 'task-a' });
      secondRequest = result.current.bindTask({ ...task, task_id: 'task-b' });
      await Promise.resolve();
    });

    await act(async () => {
      firstAccounts.resolve({ accounts: [{ id: 1 }] });
      await Promise.resolve();
      firstBind.resolve({ id: 1 });
      await firstRequest;
    });
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => {
      secondAccounts.resolve({ accounts: [] });
      await Promise.resolve();
      await secondRequest;
    });
    expect(refresh).toHaveBeenCalledOnce();
  });
});
