import { beforeEach, describe, expect, it, vi } from 'vitest';
import { monitoringApi } from '../monitoring';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const del = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: { get, post, patch, delete: del },
}));

describe('monitoringApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    patch.mockReset();
    del.mockReset();
  });

  it('uses strategy monitor endpoints for list, create, run, history, and delete', async () => {
    get.mockResolvedValue({ data: { items: [], total: 0, limit: 50, offset: 0 } });
    post.mockResolvedValue({ data: { id: 1 } });
    del.mockResolvedValue({ data: { id: 1 } });

    await monitoringApi.listStrategyMonitors();
    await monitoringApi.createStrategyMonitor({
      name: '价值策略',
      strategy_class: 'ValueStrategy',
      filepath: 'strategies/value.py',
      params: {},
      market: 'A',
      frequency: 'daily',
      symbols: ['600000'],
    });
    await monitoringApi.runStrategyMonitor(1, '2026-08-21');
    await monitoringApi.listStrategyRuns(1);
    await monitoringApi.deleteStrategyMonitor(1);

    expect(get).toHaveBeenNthCalledWith(1, '/api/v1/monitoring/strategy-monitors', expect.any(Object));
    expect(post).toHaveBeenNthCalledWith(1, '/api/v1/monitoring/strategy-monitors', expect.objectContaining({ market: 'A' }));
    expect(post).toHaveBeenNthCalledWith(2, '/api/v1/monitoring/strategy-monitors/1/run', { as_of_date: '2026-08-21' });
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/monitoring/strategy-monitors/1/runs', expect.any(Object));
    expect(del).toHaveBeenCalledWith('/api/v1/monitoring/strategy-monitors/1');
  });

  it('keeps stock lifecycle and events on stock monitor endpoints', async () => {
    get.mockResolvedValue({ data: { items: [], total: 0, limit: 50, offset: 0 } });
    post.mockResolvedValue({ data: { id: 2 } });
    del.mockResolvedValue({ data: { id: 2 } });

    await monitoringApi.listStockMonitors();
    await monitoringApi.createStockMonitor({ market: 'HK', symbol: '00005', threshold_price: 100 });
    await monitoringApi.pauseStockMonitor(2);
    await monitoringApi.resumeStockMonitor(2);
    await monitoringApi.listStockEvents(2);
    await monitoringApi.deleteStockMonitor(2);

    expect(post).toHaveBeenNthCalledWith(1, '/api/v1/monitoring/stock-monitors', { market: 'HK', symbol: '00005', threshold_price: 100 });
    expect(post).toHaveBeenNthCalledWith(2, '/api/v1/monitoring/stock-monitors/2/pause');
    expect(post).toHaveBeenNthCalledWith(3, '/api/v1/monitoring/stock-monitors/2/resume');
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/monitoring/stock-monitors/2/events', expect.any(Object));
    expect(del).toHaveBeenCalledWith('/api/v1/monitoring/stock-monitors/2');
  });
});
