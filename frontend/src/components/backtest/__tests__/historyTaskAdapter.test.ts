import { describe, expect, it } from 'vitest';
import type { TaskListItem, TaskResult } from '../../../api/backtestEngine';
import {
  buildBacktestTask,
  extractMarketLabel,
  extractParams,
  extractStrategyName,
  isMonitorTask,
} from '../historyTaskAdapter';

const flatItem = {
  task_id: 'flat-task',
  status: 'success',
  task_type: 'backtest',
  pipeline_info: {
    strategy_name: '价值策略',
    params: { frequency: 'weekly', threshold: 2 },
    symbols: ['000001.SZ'],
    market: 'A',
  },
  start_date: '2026-01-01',
  end_date: '2026-06-30',
  created_at: '2026-07-01T10:00:00',
  deleted: false,
  execution_status: 'inactive' as const,
  execution_account_id: null,
} satisfies TaskListItem;

const legacyItem = {
  ...flatItem,
  task_id: 'legacy-task',
  pipeline_info: {
    strategy_class: 'LegacyStrategy',
    strategies: [{ name: '旧策略', params: { frequency: 'daily', window: 20 } }],
    symbols: ['00700.HK'],
    market: 'HK',
  },
} satisfies TaskListItem;

describe('historyTaskAdapter', () => {
  it('reads strategy name and params from flat and legacy pipeline_info', () => {
    expect(extractStrategyName(flatItem)).toBe('价值策略');
    expect(extractParams(flatItem)).toEqual({ frequency: 'weekly', threshold: 2 });
    expect(extractStrategyName(legacyItem)).toBe('LegacyStrategy');
    expect(extractParams(legacyItem)).toEqual({ frequency: 'daily', window: 20 });
  });

  it('detects monitor tasks from task type or pipeline trigger source', () => {
    expect(isMonitorTask({ ...flatItem, task_type: 'monitor' })).toBe(true);
    expect(isMonitorTask({
      ...flatItem,
      pipeline_info: { ...flatItem.pipeline_info, trigger_source: 'monitor' },
    })).toBe(true);
    expect(isMonitorTask(flatItem)).toBe(false);
  });

  it('maps single-symbol and market labels without changing display values', () => {
    expect(extractMarketLabel(flatItem)).toBe('000001.SZ');
    expect(extractMarketLabel({
      ...flatItem,
      pipeline_info: { ...flatItem.pipeline_info, symbols: ['000001.SZ', '000002.SZ'] },
    })).toBe('A 股');
    expect(extractMarketLabel(legacyItem)).toBe('00700.HK');
  });

  it('maps a full backtest payload and prefers detail dates over list dates', () => {
    const detail = {
      ...flatItem,
      task_id: flatItem.task_id,
      pipeline_info: flatItem.pipeline_info,
      result: {
        metrics: {
          total_return: 0.12,
          annualized_return: 0.2,
          max_drawdown: -0.05,
          sharpe_ratio: 1.4,
          win_rate: 0.6,
          total_trades: 3,
          profit_factor: 1.8,
          avg_win: 20,
          avg_loss: -10,
        },
        equity_curve: [{ date: '2026-06-30', total_value: 112000 }],
        raw_trades: [{ date: '2026-02-01', symbol: '000001.SZ', direction: 'buy' as const, price: 10, shares: 100 }],
      },
    } satisfies TaskResult;

    expect(buildBacktestTask(flatItem, detail)).toMatchObject({
      taskId: 'flat-task',
      status: 'completed',
      executionStatus: 'inactive',
      executionAccountId: null,
      mode: 'single',
      strategyName: '价值策略',
      symbol: '000001.SZ',
      market: 'A',
      period: 'weekly',
      startDate: '2026-01-01',
      endDate: '2026-06-30',
      createdAt: '2026-07-01T10:00:00',
      taskType: 'backtest',
      result: {
        totalReturn: 0.12,
        equityCurve: [{ date: '2026-06-30', value: 112000 }],
        rawBuys: [{ date: '2026-02-01', symbol: '000001.SZ', price: 10, shares: 100 }],
      },
      radarPayload: null,
    });
  });

  it('keeps radar payload and lets its date range override task dates', () => {
    const radarPayload = {
      hits: [],
      total_scanned: 10,
      lookback_used: '6m',
      date_range: { start: '2026-02-01', end: '2026-08-01' },
      data_latest_date: '2026-08-01',
      strategy_class: 'RadarStrategy',
      strategy_name: '雷达策略',
      frequency: 'daily',
    };
    const radarItem = { ...flatItem, task_type: 'scan-radar' } satisfies TaskListItem;
    const detail = {
      ...radarItem,
      result: radarPayload,
      start_date: '2025-01-01',
      end_date: '2025-12-31',
    } satisfies TaskResult;

    expect(buildBacktestTask(radarItem, detail)).toMatchObject({
      taskType: 'scan-radar',
      executionStatus: 'inactive',
      executionAccountId: null,
      result: null,
      radarPayload,
      startDate: '2026-02-01',
      endDate: '2026-08-01',
    });
  });

  it('falls back to list metadata when sparse monitor detail omits pipeline_info fields', () => {
    const monitorItem = {
      ...flatItem,
      task_id: 'sparse-monitor',
      task_type: 'monitor',
      pipeline_info: {
        strategy_name: '监控策略',
        params: { frequency: 'weekly', threshold: 3 },
        symbols: ['000001.SZ'],
        market: 'A',
        trigger_source: 'monitor',
      },
      execution_status: 'active' as const,
      execution_account_id: 42,
    } satisfies TaskListItem;
    const radarPayload = {
      hits: [],
      total_scanned: 1,
      lookback_used: 'custom',
      date_range: { start: '2026-03-01', end: '2026-08-21' },
      data_latest_date: '2026-08-21',
      strategy_class: 'MonitorStrategy',
      strategy_name: '监控策略',
      frequency: 'weekly',
    };
    const sparseDetail = {
      ...monitorItem,
      pipeline_info: null,
      task_type: 'monitor',
      result: radarPayload,
      created_at: '2026-08-22T08:00:00',
    } satisfies TaskResult;

    expect(buildBacktestTask(monitorItem, sparseDetail)).toMatchObject({
      taskId: 'sparse-monitor',
      strategyName: '监控策略',
      market: 'A',
      mode: 'single',
      symbol: '000001.SZ',
      period: 'weekly',
      params: { frequency: 'weekly', threshold: 3 },
      taskType: 'monitor',
      executionStatus: 'active',
      executionAccountId: 42,
      createdAt: '2026-08-22T08:00:00',
      result: null,
      radarPayload,
      startDate: '2026-03-01',
      endDate: '2026-08-21',
    });
  });

  it('shallow-merges partial detail pipeline_info over list pipeline_info', () => {
    const detail = {
      ...flatItem,
      pipeline_info: { strategy_name: '详情策略', params: { frequency: 'monthly' } },
      result: null,
    } satisfies TaskResult;

    expect(buildBacktestTask(flatItem, detail)).toMatchObject({
      strategyName: '详情策略',
      market: 'A',
      mode: 'single',
      symbol: '000001.SZ',
      period: 'monthly',
      params: { frequency: 'monthly' },
    });
  });

  it('keeps the legacy fallback when merged pipeline_info has no strategy fields', () => {
    const item = { ...flatItem, pipeline_info: { market: 'A' } } satisfies TaskListItem;
    const detail = { ...item, pipeline_info: { symbols: ['000001.SZ'] }, result: null } satisfies TaskResult;

    expect(buildBacktestTask(item, detail).strategyName).toBe('旧版任务');
  });
});
