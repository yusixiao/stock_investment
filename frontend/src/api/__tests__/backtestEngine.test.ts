import { beforeEach, describe, expect, it, vi } from 'vitest';
import { backtestEngineApi } from '../backtestEngine';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: {
    get,
    post,
    delete: del,
  },
}));

describe('backtestEngineApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    del.mockReset();
  });

  it('listStrategies maps frequency_overridable to camelCase', async () => {
    get.mockResolvedValueOnce({
      data: [
        {
          filepath: '/strategies/foo.py',
          class_name: 'FooStrategy',
          name: 'Foo',
          strategy_type: 'strategy',
          frequency: 'monthly',
          frequency_overridable: false,
          params: {},
        },
      ],
    });
    const list = await backtestEngineApi.listStrategies();
    expect(list[0].frequencyOverridable).toBe(false);
    expect(list[0].className).toBe('FooStrategy');
    expect(list[0].frequency).toBe('monthly');
  });

  it('runBacktest posts flat payload with strategy_class', async () => {
    post.mockResolvedValueOnce({ data: { task_id: 'abc', status: 'running' } });
    await backtestEngineApi.runBacktest({
      strategy_class: 'FooStrategy',
      filepath: '/strategies/foo.py',
      params: { window: 20 },
      start_date: '2023-01-01',
      end_date: '2024-01-01',
      market: 'A',
    });
    expect(post).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({
        strategy_class: 'FooStrategy',
        filepath: '/strategies/foo.py',
        params: { window: 20 },
        market: 'A',
      }),
    );
    // 不应再发送旧字段
    const payload = post.mock.calls[0][1];
    expect(payload).not.toHaveProperty('pipeline');
    expect(payload).not.toHaveProperty('param_overrides');
  });

  it('listTasks forwards show_deleted query', async () => {
    get.mockResolvedValueOnce({ data: [] });
    await backtestEngineApi.listTasks(true);
    expect(get).toHaveBeenCalledWith(
      '/api/backtest/tasks',
      expect.objectContaining({ params: { show_deleted: true } }),
    );
  });

  it('deleteTask issues DELETE request', async () => {
    del.mockResolvedValueOnce({ data: { ok: true } });
    await backtestEngineApi.deleteTask('abc');
    expect(del).toHaveBeenCalledWith('/api/backtest/tasks/abc');
  });
});
