import apiClient from './index';

export interface StrategyInfo {
  filepath: string;
  className: string;
  name: string;
  strategyType: string;
  frequency?: string;
  params?: Record<string, { default: unknown; description?: string }>;
}

export interface RunBacktestRequest {
  pipeline: { filepath: string; class_name: string }[];
  start_date: string;
  end_date: string;
  symbols?: string[];
  param_overrides?: Record<string, Record<string, unknown>>;
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
  equity_curve?: { date: string; value: number }[];
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
  screened_symbols?: unknown[];
}

export interface TaskListItem {
  task_id: string;
  status: string;
  task_type: string;
  pipeline_info: string | null;
  start_date: string | null;
  end_date: string | null;
  summary: string | null;
  created_at: string;
}

export const backtestEngineApi = {
  async listStrategies(): Promise<StrategyInfo[]> {
    const resp = await apiClient.get('/api/backtest/strategies');
    return resp.data.map((s: Record<string, unknown>) => ({
      filepath: s.filepath,
      className: s.class_name,
      name: s.name,
      strategyType: s.strategy_type,
      frequency: s.frequency,
      params: s.params,
    }));
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

  async listTasks(): Promise<TaskListItem[]> {
    const resp = await apiClient.get('/api/backtest/tasks');
    return resp.data;
  },

  async deleteTask(taskId: string): Promise<void> {
    await apiClient.delete(`/api/backtest/tasks/${taskId}`);
  },
};
