import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMonitorCenter } from '../useMonitorCenter';

const monitoringApi = vi.hoisted(() => ({ getCenter: vi.fn() }));
const backtestEngineApi = vi.hoisted(() => ({ listStrategies: vi.fn() }));

vi.mock('../../../api/monitoring', () => ({ monitoringApi }));
vi.mock('../../../api/backtestEngine', () => ({ backtestEngineApi }));

const snapshot = (symbol: string) => ({
  strategies: [], strategy_runs: {},
  stocks: [{ id: 1, market: 'A', symbol, name: null, threshold_price: 10, is_active: true, state: 'armed', last_price: null, last_price_date: null, last_triggered_at: null, created_at: '', updated_at: '' }],
  stock_events: {}, generated_at: symbol,
});

describe('useMonitorCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    backtestEngineApi.listStrategies.mockResolvedValue([]);
  });

  it('keeps the newest refresh snapshot when an older response resolves last', async () => {
    let resolveFirst!: (value: ReturnType<typeof snapshot>) => void;
    let resolveSecond!: (value: ReturnType<typeof snapshot>) => void;
    monitoringApi.getCenter
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
    const { result } = renderHook(() => useMonitorCenter());

    await waitFor(() => expect(monitoringApi.getCenter).toHaveBeenCalledTimes(1));
    await act(async () => { void result.current.refresh(); });
    resolveSecond(snapshot('newest'));
    await waitFor(() => expect(result.current.stocks[0]?.symbol).toBe('newest'));
    resolveFirst(snapshot('stale'));
    await act(async () => { await Promise.resolve(); });

    expect(result.current.stocks[0]?.symbol).toBe('newest');
    expect(result.current).not.toHaveProperty('setStrategies');
    expect(result.current).not.toHaveProperty('setStocks');
  });
});
