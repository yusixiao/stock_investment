import apiClient from './index';

export type MonitoringMarket = 'A' | 'HK' | 'US';
export type MonitoringFrequency = 'daily' | 'weekly' | 'monthly' | 'quarterly';
export type StrategyLastRunStatus = 'pending' | 'running' | 'success' | 'failed';
export type StrategyRunStatus = 'running' | 'success' | 'failed';
export type StockMonitorState = 'armed' | 'triggered' | 'paused';
export type StockEventStatus = 'recorded' | 'notified';

export interface StrategyMonitor {
  id: number;
  name: string;
  strategy_class: string;
  filepath: string;
  params: Record<string, unknown>;
  market: MonitoringMarket;
  frequency: MonitoringFrequency;
  symbols: string[] | null;
  is_active: boolean;
  next_run_date: string | null;
  last_run_at: string | null;
  last_run_status: StrategyLastRunStatus;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface StrategyRun {
  id: number;
  monitor_id: number;
  scheduled_date: string;
  started_at: string;
  finished_at: string | null;
  status: StrategyRunStatus;
  task_id: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface StockMonitor {
  id: number;
  market: MonitoringMarket;
  symbol: string;
  name: string | null;
  threshold_price: number;
  is_active: boolean;
  state: StockMonitorState;
  last_price: number | null;
  last_price_date: string | null;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StockEvent {
  id: number;
  monitor_id: number;
  market: MonitoringMarket;
  symbol: string;
  observed_price: number;
  threshold_price: number;
  observed_date: string;
  triggered_at: string;
  status: StockEventStatus;
}

export interface MonitorPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreateStrategyMonitorRequest {
  name: string;
  strategy_class: string;
  filepath: string;
  params?: Record<string, unknown>;
  market: MonitoringMarket;
  frequency: MonitoringFrequency;
  symbols?: string[];
  next_run_date?: string;
}

export interface CreateStockMonitorRequest {
  market: MonitoringMarket;
  symbol: string;
  threshold_price: number;
}

export interface UpdateStrategyMonitorRequest {
  name?: string;
  strategy_class?: string;
  filepath?: string;
  params?: Record<string, unknown>;
  market?: MonitoringMarket;
  frequency?: MonitoringFrequency;
  symbols?: string[];
  next_run_date?: string;
}

export interface UpdateStockMonitorRequest {
  market?: MonitoringMarket;
  symbol?: string;
  threshold_price?: number;
  name?: string;
}

const pageParams = { limit: 50, offset: 0 };

export const monitoringApi = {
  async listStrategyMonitors(): Promise<MonitorPage<StrategyMonitor>> {
    const response = await apiClient.get('/api/v1/monitoring/strategy-monitors', { params: pageParams });
    return response.data;
  },

  async createStrategyMonitor(payload: CreateStrategyMonitorRequest): Promise<StrategyMonitor> {
    const response = await apiClient.post('/api/v1/monitoring/strategy-monitors', payload);
    return response.data;
  },

  async runStrategyMonitor(id: number, asOfDate: string): Promise<StrategyRun> {
    const response = await apiClient.post(`/api/v1/monitoring/strategy-monitors/${id}/run`, { as_of_date: asOfDate });
    return response.data;
  },

  async listStrategyRuns(id: number): Promise<MonitorPage<StrategyRun>> {
    const response = await apiClient.get(`/api/v1/monitoring/strategy-monitors/${id}/runs`, { params: pageParams });
    return response.data;
  },

  async deleteStrategyMonitor(id: number): Promise<StrategyMonitor> {
    const response = await apiClient.delete(`/api/v1/monitoring/strategy-monitors/${id}`);
    return response.data;
  },

  async updateStrategyMonitor(id: number, payload: UpdateStrategyMonitorRequest): Promise<StrategyMonitor> {
    const response = await apiClient.patch(`/api/v1/monitoring/strategy-monitors/${id}`, payload);
    return response.data;
  },

  async listStockMonitors(): Promise<MonitorPage<StockMonitor>> {
    const response = await apiClient.get('/api/v1/monitoring/stock-monitors', { params: pageParams });
    return response.data;
  },

  async createStockMonitor(payload: CreateStockMonitorRequest): Promise<StockMonitor> {
    const response = await apiClient.post('/api/v1/monitoring/stock-monitors', payload);
    return response.data;
  },

  async updateStockMonitor(id: number, payload: UpdateStockMonitorRequest): Promise<StockMonitor> {
    const response = await apiClient.patch(`/api/v1/monitoring/stock-monitors/${id}`, payload);
    return response.data;
  },

  async pauseStockMonitor(id: number): Promise<StockMonitor> {
    const response = await apiClient.post(`/api/v1/monitoring/stock-monitors/${id}/pause`);
    return response.data;
  },

  async resumeStockMonitor(id: number): Promise<StockMonitor> {
    const response = await apiClient.post(`/api/v1/monitoring/stock-monitors/${id}/resume`);
    return response.data;
  },

  async listStockEvents(id: number): Promise<MonitorPage<StockEvent>> {
    const response = await apiClient.get(`/api/v1/monitoring/stock-monitors/${id}/events`, { params: pageParams });
    return response.data;
  },

  async deleteStockMonitor(id: number): Promise<StockMonitor> {
    const response = await apiClient.delete(`/api/v1/monitoring/stock-monitors/${id}`);
    return response.data;
  },
};
