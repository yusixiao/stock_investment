/**
 * 全市场回测数据缓存 API。
 */

export type CacheMarket = 'A' | 'HK' | 'US';

export interface MarketCacheStatus {
  market: CacheMarket;
  status: 'idle' | 'loading' | 'loaded' | 'failed';
  loaded: boolean;
  symbols: number;
  valuation_count: number;
  dividend_count: number;
  financial_count: number;
  loaded_at: number;
  /** 数据截止日 YYYY-MM-DD;未加载时为 null */
  last_date: string | null;
  progress: { current: number; total: number; phase: string };
  error: string | null;
  elapsed: number;
}

export type CacheStatusMap = Record<CacheMarket, MarketCacheStatus>;

const BASE = '/api/backtest/cache';

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const backtestCacheApi = {
  status: () => jsonFetch<CacheStatusMap>(`${BASE}/status`),
  load: (market: CacheMarket) =>
    jsonFetch<MarketCacheStatus>(`${BASE}/load`, {
      method: 'POST',
      body: JSON.stringify({ market }),
    }),
  invalidate: (market: CacheMarket) =>
    jsonFetch<{ ok: boolean; market: string }>(`${BASE}/${market}`, {
      method: 'DELETE',
    }),
};
