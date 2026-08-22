import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMonitorActions } from '../useMonitorActions';

const monitoringApi = vi.hoisted(() => ({
  createStrategyMonitor: vi.fn(),
  runStrategyMonitor: vi.fn(),
  listStrategyRuns: vi.fn(),
  listStrategyMonitors: vi.fn(),
  createStockMonitor: vi.fn(),
  pauseStockMonitor: vi.fn(),
  resumeStockMonitor: vi.fn(),
  deleteStockMonitor: vi.fn(),
  deleteStrategyMonitor: vi.fn(),
}));

vi.mock('../../../api/monitoring', () => ({ monitoringApi }));

const strategy = { filepath: 'value.py', className: 'ValueStrategy', name: '价值策略' };
const stock = { id: 2, market: 'A' as const, symbol: '600000', threshold_price: 10, state: 'armed' as const };

function setup() {
  return renderHook(() => useMonitorActions({
    onStrategyChanged: vi.fn(),
    onStockChanged: vi.fn(),
  }));
}

describe('useMonitorActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    monitoringApi.listStrategyRuns.mockResolvedValue({ items: [] });
    monitoringApi.listStrategyMonitors.mockResolvedValue({ items: [] });
    monitoringApi.createStrategyMonitor.mockResolvedValue({ id: 1 });
    monitoringApi.runStrategyMonitor.mockResolvedValue({ id: 1 });
    monitoringApi.createStockMonitor.mockResolvedValue(stock);
    monitoringApi.pauseStockMonitor.mockResolvedValue({ ...stock, state: 'paused' });
    monitoringApi.resumeStockMonitor.mockResolvedValue(stock);
    monitoringApi.deleteStockMonitor.mockResolvedValue(undefined);
    monitoringApi.deleteStrategyMonitor.mockResolvedValue(undefined);
  });

  it('clears strategy create and run errors before new submissions and after success', async () => {
    monitoringApi.createStrategyMonitor.mockRejectedValueOnce(new Error('create failed'));
    const { result } = setup();

    await act(async () => {
      await result.current.saveStrategy({ name: '价值策略', selectedStrategy: strategy, market: 'A', frequency: 'daily', symbols: '' });
    });
    expect(result.current.createStrategyError).toBe('策略监控创建失败，请检查配置');
    monitoringApi.createStrategyMonitor.mockResolvedValueOnce({ id: 1 });
    await act(async () => {
      await result.current.saveStrategy({ name: '价值策略', selectedStrategy: strategy, market: 'A', frequency: 'daily', symbols: '' });
    });
    expect(result.current.createStrategyError).toBeNull();

    monitoringApi.runStrategyMonitor.mockRejectedValueOnce(new Error('run failed'));
    await act(async () => { await result.current.runStrategy(1); });
    expect(result.current.strategyActionError).toBe('运行策略监控失败，请稍后重试');
    await act(async () => { await result.current.runStrategy(1); });
    expect(result.current.strategyActionError).toBeNull();
  });

  it('clears stock create, pause, resume, and delete errors after successful retry', async () => {
    const { result } = setup();
    monitoringApi.createStockMonitor.mockRejectedValueOnce(new Error('create failed'));
    await act(async () => { await result.current.saveStock({ market: 'A', symbol: '600000', threshold: '10' }); });
    expect(result.current.stockActionError).toBe('股票价格监控创建失败，请检查配置');
    await act(async () => { await result.current.saveStock({ market: 'A', symbol: '600000', threshold: '10' }); });
    expect(result.current.stockActionError).toBeNull();

    for (const [method, action, message] of [
      ['pauseStockMonitor', { kind: 'pause', monitor: stock }, '暂停股票监控失败，请稍后重试'],
      ['resumeStockMonitor', { kind: 'resume', monitor: { ...stock, state: 'paused' } }, '恢复股票监控失败，请稍后重试'],
      ['deleteStockMonitor', { kind: 'delete-stock', id: stock.id, label: stock.symbol }, '删除股票监控失败，请稍后重试'],
    ] as const) {
      monitoringApi[method].mockRejectedValueOnce(new Error('action failed'));
      await act(async () => { await result.current.confirmAction(action); });
      expect(result.current.stockActionError).toBe(message);
      monitoringApi[method].mockResolvedValueOnce(method === 'deleteStockMonitor' ? undefined : stock);
      await act(async () => { await result.current.confirmAction(action); });
      expect(result.current.stockActionError).toBeNull();
    }
  });

  it('clears strategy delete errors after a successful retry', async () => {
    const { result } = setup();
    const action = { kind: 'delete-strategy' as const, id: 1, label: '价值策略' };
    monitoringApi.deleteStrategyMonitor.mockRejectedValueOnce(new Error('delete failed'));
    await act(async () => { await result.current.confirmAction(action); });
    expect(result.current.strategyActionError).toBe('删除策略监控失败，请稍后重试');
    await act(async () => { await result.current.confirmAction(action); });
    expect(result.current.strategyActionError).toBeNull();
  });
});
