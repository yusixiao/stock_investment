import { useEffect, useRef, useState } from 'react';
import { backtestEngineApi } from '../../api/backtestEngine';
import type { StrategyInfo } from '../../api/backtestEngine';
import { monitoringApi } from '../../api/monitoring';
import type { MonitorCenterSnapshot } from '../../api/monitoring';

const emptySnapshot: MonitorCenterSnapshot = {
  strategies: [],
  strategy_runs: {},
  stocks: [],
  stock_events: {},
  generated_at: '',
};

export const useMonitorCenter = () => {
  const [snapshot, setSnapshot] = useState<MonitorCenterSnapshot>(emptySnapshot);
  const requestSequence = useRef(0);
  const [strategyCatalog, setStrategyCatalog] = useState<StrategyInfo[]>([]);
  const [strategyCatalogLoading, setStrategyCatalogLoading] = useState(true);
  const [strategyCatalogError, setStrategyCatalogError] = useState<string | null>(null);
  const [monitorLoading, setMonitorLoading] = useState(true);
  const [loadStrategyError, setLoadStrategyError] = useState<string | null>(null);
  const [loadStockError, setLoadStockError] = useState<string | null>(null);

  const refresh = async () => {
    const sequence = ++requestSequence.current;
    setMonitorLoading(true);
    try {
      const nextSnapshot = await monitoringApi.getCenter();
      if (sequence !== requestSequence.current) return;
      setSnapshot(nextSnapshot);
      setLoadStrategyError(null);
      setLoadStockError(null);
    } catch {
      if (sequence !== requestSequence.current) return;
      setLoadStrategyError('策略监控加载失败，请稍后重试');
      setLoadStockError('股票价格监控加载失败，请稍后重试');
    } finally {
      if (sequence === requestSequence.current) setMonitorLoading(false);
    }
  };

  const loadStrategyCatalog = async () => {
    setStrategyCatalogLoading(true);
    try {
      setStrategyCatalog(await backtestEngineApi.listStrategies());
      setStrategyCatalogError(null);
    } catch {
      setStrategyCatalog([]);
      setStrategyCatalogError('策略目录加载失败，请稍后重试');
    } finally {
      setStrategyCatalogLoading(false);
    }
  };

  /* eslint-disable react-hooks/set-state-in-effect -- initial data load synchronizes remote monitor collections. */
  useEffect(() => {
    void refresh();
    void loadStrategyCatalog();
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  return {
    strategies: snapshot.strategies,
    strategyRuns: snapshot.strategy_runs,
    stocks: snapshot.stocks,
    stockEvents: snapshot.stock_events,
    strategyLoading: monitorLoading,
    strategyCatalog, strategyCatalogLoading, strategyCatalogError,
    stockLoading: monitorLoading, loadStrategyError, loadStockError,
    refresh,
    loadStrategies: refresh,
    loadStocks: refresh,
  };
};
