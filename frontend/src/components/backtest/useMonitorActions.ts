import { useState } from 'react';
import type { StrategyInfo } from '../../api/backtestEngine';
import { monitoringApi } from '../../api/monitoring';
import type { MonitoringFrequency, MonitoringMarket, StockMonitor, StrategyMonitor, StrategyRun } from '../../api/monitoring';

type PendingAction =
  | { kind: 'pause' | 'resume'; monitor: StockMonitor }
  | { kind: 'delete-stock' | 'delete-strategy'; id: number; label: string };

interface MonitorChange {
  createdStrategy?: StrategyMonitor;
  updatedStrategies?: StrategyMonitor[];
  deletedStrategyId?: number;
  strategyRuns?: Record<number, StrategyRun[]>;
  createdStock?: StockMonitor;
  updatedStock?: StockMonitor;
  deletedStockId?: number;
}

export const useMonitorActions = ({ onStrategyChanged, onStockChanged }: {
  onStrategyChanged: (change: MonitorChange) => void;
  onStockChanged: (change: MonitorChange) => void;
}) => {
  const [stockFormErrors, setStockFormErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [runningStrategyId, setRunningStrategyId] = useState<number | null>(null);
  const [strategyActionError, setStrategyActionError] = useState<string | null>(null);
  const [stockActionError, setStockActionError] = useState<string | null>(null);
  const [createStrategyError, setCreateStrategyError] = useState<string | null>(null);

  const saveStrategy = async ({ name, selectedStrategy, market, frequency, symbols }: { name: string; selectedStrategy?: StrategyInfo; market: MonitoringMarket; frequency: MonitoringFrequency; symbols: string }) => {
    setCreateStrategyError(null);
    const trimmedName = name.trim();
    if (!trimmedName || !selectedStrategy) return false;
    setSaving(true);
    try {
      const symbolList = symbols.split(',').map((symbol) => symbol.trim()).filter(Boolean);
      const created = await monitoringApi.createStrategyMonitor({ name: trimmedName, strategy_class: selectedStrategy.className, filepath: selectedStrategy.filepath, params: {}, market, frequency, symbols: symbolList.length > 0 ? symbolList : undefined });
      onStrategyChanged({ createdStrategy: created, strategyRuns: { [created.id]: [] } });
      setCreateStrategyError(null);
      return true;
    } catch {
      setCreateStrategyError('策略监控创建失败，请检查配置');
      return false;
    } finally {
      setSaving(false);
    }
  };

  const runStrategy = async (monitorId: number) => {
    setRunningStrategyId(monitorId);
    setStrategyActionError(null);
    try {
      await monitoringApi.runStrategyMonitor(monitorId, new Date().toISOString().slice(0, 10));
      const page = await monitoringApi.listStrategyRuns(monitorId);
      onStrategyChanged({ strategyRuns: { [monitorId]: page.items } });
      const monitors = await monitoringApi.listStrategyMonitors();
      onStrategyChanged({ updatedStrategies: monitors.items });
    } catch {
      try {
        const page = await monitoringApi.listStrategyRuns(monitorId);
        onStrategyChanged({ strategyRuns: { [monitorId]: page.items } });
      } catch {
        // Keep the run error visible even if the follow-up history request also fails.
      }
      setStrategyActionError('运行策略监控失败，请稍后重试');
    } finally {
      setRunningStrategyId(null);
    }
  };

  const saveStock = async ({ market, symbol, threshold }: { market: string; symbol: string; threshold: string }) => {
    setStockActionError(null);
    const errors: Record<string, string> = {};
    if (!market) errors.market = '请选择市场';
    if (!symbol.trim()) errors.symbol = '请输入股票代码';
    const price = Number(threshold);
    if (!threshold || !Number.isFinite(price) || price <= 0) errors.threshold = '请输入正数阈值';
    setStockFormErrors(errors);
    if (Object.keys(errors).length > 0) return false;
    setSaving(true);
    try {
      const created = await monitoringApi.createStockMonitor({ market: market as MonitoringMarket, symbol: symbol.trim().toUpperCase(), threshold_price: price });
      onStockChanged({ createdStock: created });
      setStockFormErrors({});
      setStockActionError(null);
      return true;
    } catch {
      setStockActionError('股票价格监控创建失败，请检查配置');
      return false;
    } finally {
      setSaving(false);
    }
  };

  const confirmAction = async (action: PendingAction | null) => {
    if (!action) return;
    const isStockAction = action.kind === 'pause' || action.kind === 'resume' || action.kind === 'delete-stock';
    if (isStockAction) setStockActionError(null);
    else setStrategyActionError(null);
    try {
      if (action.kind === 'pause' || action.kind === 'resume') {
        const updated = action.kind === 'pause' ? await monitoringApi.pauseStockMonitor(action.monitor.id) : await monitoringApi.resumeStockMonitor(action.monitor.id);
        onStockChanged({ updatedStock: updated });
      } else if (action.kind === 'delete-stock') {
        await monitoringApi.deleteStockMonitor(action.id);
        onStockChanged({ deletedStockId: action.id });
      } else if (action.kind === 'delete-strategy') {
        await monitoringApi.deleteStrategyMonitor(action.id);
        onStrategyChanged({ deletedStrategyId: action.id });
      }
      if (isStockAction) setStockActionError(null);
      else setStrategyActionError(null);
    } catch {
      if (action.kind === 'pause' || action.kind === 'resume' || action.kind === 'delete-stock') setStockActionError(`${action.kind === 'pause' ? '暂停' : action.kind === 'resume' ? '恢复' : '删除'}股票监控失败，请稍后重试`);
      else setStrategyActionError('删除策略监控失败，请稍后重试');
    }
  };

  return { stockFormErrors, saving, runningStrategyId, createStrategyError, strategyActionError, stockActionError, saveStrategy, runStrategy, saveStock, confirmAction };
};
