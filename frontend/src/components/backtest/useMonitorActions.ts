import { useState } from 'react';
import type { StrategyInfo } from '../../api/backtestEngine';
import { monitoringApi } from '../../api/monitoring';
import type { MonitoringFrequency, MonitoringMarket, StockMonitor } from '../../api/monitoring';

type PendingAction =
  | { kind: 'pause' | 'resume'; monitor: StockMonitor }
  | { kind: 'delete-stock' | 'delete-strategy'; id: number; label: string };

export const useMonitorActions = ({ onRefresh }: {
  onRefresh: () => void | Promise<void>;
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
      await monitoringApi.createStrategyMonitor({ name: trimmedName, strategy_class: selectedStrategy.className, filepath: selectedStrategy.filepath, params: {}, market, frequency, symbols: symbolList.length > 0 ? symbolList : undefined });
      await onRefresh();
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
      await onRefresh();
    } catch {
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
      await monitoringApi.createStockMonitor({ market: market as MonitoringMarket, symbol: symbol.trim().toUpperCase(), threshold_price: price });
      await onRefresh();
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
        await (action.kind === 'pause' ? monitoringApi.pauseStockMonitor(action.monitor.id) : monitoringApi.resumeStockMonitor(action.monitor.id));
        await onRefresh();
      } else if (action.kind === 'delete-stock') {
        await monitoringApi.deleteStockMonitor(action.id);
        await onRefresh();
      } else if (action.kind === 'delete-strategy') {
        await monitoringApi.deleteStrategyMonitor(action.id);
        await onRefresh();
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
