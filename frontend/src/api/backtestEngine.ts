import apiClient from './index';

export interface StrategyInfo {
  filepath: string;
  className: string;
  name: string;
  strategyType: string;
  frequency?: string;
  frequencyOverridable: boolean;
  params?: Record<string, { default: unknown; label?: string; description?: string; type?: string }>;
}

// Phase 5: 单策略扁平 payload
export interface RunBacktestRequest {
  strategy_class: string;
  filepath: string;
  params?: Record<string, unknown>;
  frequency_override?: string;
  start_date: string;
  end_date: string;
  symbols?: string[];
  market?: string;
  source_task_id?: string;
}

export interface TaskStatus {
  task_id: string;
  status: 'running' | 'success' | 'failed';
  progress?: { current: number; total: number; phase: string };
}

export interface TaskResult {
  task_id: string;
  status: string;
  task_type: string;
  pipeline_info: unknown;
  start_date: string;
  end_date: string;
  result: BacktestResultPayload | null;
  error?: string;
  created_at: string;
}

export interface BacktestResultPayload {
  metrics?: {
    total_return: number;
    annualized_return: number;
    max_drawdown: number;
    sharpe_ratio: number;
    win_rate: number;
    total_trades: number;
    profit_factor: number;
    avg_win: number;
    avg_loss: number;
  };
  equity_curve?: { date: string; value?: number; total_value?: number }[];
  trades?: {
    symbol: string;
    entry_date: string;
    exit_date: string;
    direction: string;
    entry_price: number;
    exit_price: number;
    shares: number;
    pnl: number;
    pnl_pct: number;
    hold_days: number;
  }[];
  raw_trades?: {
    date: string;
    symbol: string;
    direction: 'buy' | 'sell';
    price: number;
    shares: number;
    commission?: number;
    tax?: number;
    amount?: number;
  }[];
  screened_symbols?: unknown[];
  // 每个交易过的 symbol 在回测结束日的收盘价 → 前端汇总「当前价」与未实现盈亏
  end_prices?: Record<string, number>;
}

export interface TaskPipelineInfo {
  strategy_class?: string;
  strategy_name?: string;
  params?: Record<string, unknown>;
  frequency?: string;
  symbols?: string[];
  market?: string;
  // 旧任务可能存 {strategies: [...]} 嵌套结构
  strategies?: Array<Record<string, unknown>>;
}

export interface TaskListItem {
  task_id: string;
  status: string;
  task_type: string;
  pipeline_info?: TaskPipelineInfo;
  start_date: string | null;
  end_date: string | null;
  summary?: Record<string, unknown>;
  created_at: string;
  deleted: boolean;
  source_task_id?: string;
}

export const backtestEngineApi = {
  async listStrategies(): Promise<StrategyInfo[]> {
    const resp = await apiClient.get('/api/backtest/strategies');
    return resp.data.map((s: Record<string, unknown>) => ({
      filepath: s.filepath as string,
      className: s.class_name as string,
      name: s.name as string,
      strategyType: s.strategy_type as string,
      frequency: s.frequency as string | undefined,
      frequencyOverridable: Boolean(s.frequency_overridable),
      params: s.params as StrategyInfo['params'],
    }));
  },

  async listTasks(showDeleted = false): Promise<TaskListItem[]> {
    const resp = await apiClient.get('/api/backtest/tasks', {
      params: { show_deleted: showDeleted },
    });
    return resp.data;
  },

  async runBacktest(req: RunBacktestRequest): Promise<{ task_id: string; status: string }> {
    const resp = await apiClient.post('/api/backtest/run', req);
    return resp.data;
  },

  async getStatus(taskId: string): Promise<TaskStatus> {
    const resp = await apiClient.get(`/api/backtest/status/${taskId}`);
    return resp.data;
  },

  async getResult(taskId: string): Promise<TaskResult> {
    const resp = await apiClient.get(`/api/backtest/result/${taskId}`);
    return resp.data;
  },

  async deleteTask(taskId: string): Promise<void> {
    await apiClient.delete(`/api/backtest/tasks/${taskId}`);
  },

  async scanRadar(req: ScanRadarRequest): Promise<{ task_id: string; status: string }> {
    const resp = await apiClient.post('/api/backtest/scan-radar', req);
    return resp.data;
  },

  async getScanRadarResult(taskId: string): Promise<ScanRadarTaskResult> {
    const resp = await apiClient.get(`/api/backtest/scan-radar/result/${taskId}`);
    return resp.data;
  },
};

export type RadarLookback = 'yesterday' | '1m' | '6m' | '1y' | '3y' | '5y';

export interface ScanRadarRequest {
  strategy_class: string;
  filepath: string;
  params?: Record<string, unknown>;
  lookback: RadarLookback;
  market?: string;
}

export interface ScanRadarHit {
  symbol: string;
  name: string | null;
  current_price: number;
  signal_close: number | null;
  change_pct_since_signal: number | null;
  last_match_date: string;
  match_count: number;
  factors: Record<string, number | string | null>;
}

export interface ScanRadarPayload {
  hits: ScanRadarHit[];
  total_scanned: number;
  lookback_used: RadarLookback;
  date_range: { start: string; end: string };
  data_latest_date: string;
  strategy_class: string;
  strategy_name: string;
  frequency: string;
}

export interface ScanRadarTaskResult {
  task_id: string;
  status: 'running' | 'success' | 'failed';
  result: ScanRadarPayload | null;
  error?: string;
}
