import { useEffect, useState } from 'react';
import { backtestEngineApi } from '../../api/backtestEngine';
import type { StrategyInfo } from '../../api/backtestEngine';
import { monitoringApi } from '../../api/monitoring';
import type { StockEvent, StockMonitor, StrategyMonitor, StrategyRun } from '../../api/monitoring';

export const useMonitorCenter = () => {
  const [strategies, setStrategies] = useState<StrategyMonitor[]>([]);
  const [strategyRuns, setStrategyRuns] = useState<Record<number, StrategyRun[]>>({});
  const [stocks, setStocks] = useState<StockMonitor[]>([]);
  const [stockEvents, setStockEvents] = useState<Record<number, StockEvent[]>>({});
  const [strategyLoading, setStrategyLoading] = useState(true);
  const [strategyCatalog, setStrategyCatalog] = useState<StrategyInfo[]>([]);
  const [strategyCatalogLoading, setStrategyCatalogLoading] = useState(true);
  const [strategyCatalogError, setStrategyCatalogError] = useState<string | null>(null);
  const [stockLoading, setStockLoading] = useState(true);
  const [loadStrategyError, setLoadStrategyError] = useState<string | null>(null);
  const [loadStockError, setLoadStockError] = useState<string | null>(null);

  const loadStrategies = async () => {
    setStrategyLoading(true);
    try {
      const page = await monitoringApi.listStrategyMonitors();
      setStrategies(page.items);
      setLoadStrategyError(null);
      const runs = await Promise.all(page.items.map(async (monitor) => [monitor.id, (await monitoringApi.listStrategyRuns(monitor.id)).items] as const));
      setStrategyRuns(Object.fromEntries(runs));
    } catch {
      setLoadStrategyError('策略监控加载失败，请稍后重试');
    } finally {
      setStrategyLoading(false);
    }
  };

  const loadStocks = async () => {
    setStockLoading(true);
    try {
      const page = await monitoringApi.listStockMonitors();
      setStocks(page.items);
      setLoadStockError(null);
      const events = await Promise.all(page.items.map(async (monitor) => [monitor.id, (await monitoringApi.listStockEvents(monitor.id)).items] as const));
      setStockEvents(Object.fromEntries(events));
    } catch {
      setLoadStockError('股票价格监控加载失败，请稍后重试');
    } finally {
      setStockLoading(false);
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
    void loadStrategies();
    void loadStocks();
    void loadStrategyCatalog();
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  return {
    strategies, setStrategies, strategyRuns, setStrategyRuns, stocks, setStocks, stockEvents, setStockEvents,
    strategyLoading, strategyCatalog, strategyCatalogLoading, strategyCatalogError, stockLoading, loadStrategyError, loadStockError,
    loadStrategies, loadStocks,
  };
};
