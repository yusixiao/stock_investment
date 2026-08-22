import type React from 'react';
import { useState } from 'react';
import { RiAddLine, RiDeleteBinLine, RiPauseLine, RiPlayLine, RiRefreshLine } from '@remixicon/react';
import type {
  MonitoringFrequency,
  MonitoringMarket,
  StockMonitorState,
  StockMonitor,
  StrategyLastRunStatus,
  StrategyRun,
} from '../../api/monitoring';
import { Badge, Button, Card, ConfirmDialog, Input, Select } from '../common';
import { useMonitorActions } from './useMonitorActions';
import { useMonitorCenter } from './useMonitorCenter';

type PendingAction =
  | { kind: 'pause' | 'resume'; monitor: StockMonitor }
  | { kind: 'delete-stock' | 'delete-strategy'; id: number; label: string }
  | null;

const marketOptions = [
  { value: 'A', label: 'A 股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
];

const frequencyOptions = [
  { value: 'daily', label: '每日' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' },
  { value: 'quarterly', label: '每季度' },
];

const statusLabel = (status: StrategyLastRunStatus | StrategyRun['status']) => ({ pending: '待运行', success: '成功', failed: '失败', running: '运行中' }[status]);
const stateLabel = (state: StockMonitorState) => ({ armed: '已布防', paused: '已暂停', triggered: '已触发' }[state]);
const marketLabel = (market: MonitoringMarket) => ({ A: 'A 股', HK: '港股', US: '美股' }[market]);

const MarketMonitor: React.FC = () => {
  const center = useMonitorCenter();
  const [showStrategyForm, setShowStrategyForm] = useState(false);
  const [showStockForm, setShowStockForm] = useState(false);
  const [strategyName, setStrategyName] = useState('');
  const [strategyMarket, setStrategyMarket] = useState<MonitoringMarket>('A');
  const [strategySymbols, setStrategySymbols] = useState('');
  const [frequency, setFrequency] = useState<MonitoringFrequency>('daily');
  const [stockMarket, setStockMarket] = useState('');
  const [stockSymbol, setStockSymbol] = useState('');
  const [threshold, setThreshold] = useState('');
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const { strategies, strategyRuns, stocks, stockEvents, strategyLoading, strategyCatalog, strategyCatalogLoading, strategyCatalogError, stockLoading, loadStrategyError, loadStockError, loadStrategies, loadStocks } = center;
  const stockError = loadStockError;
  const selectedStrategy = strategyCatalog.find((strategy) => strategy.name === strategyName);
  const { stockFormErrors, saving, runningStrategyId, createStrategyError, strategyActionError, stockActionError, saveStrategy: saveStrategyAction, runStrategy, saveStock: saveStockAction, confirmAction: confirmMonitorAction } = useMonitorActions({
    onStrategyChanged: ({ createdStrategy, updatedStrategies, deletedStrategyId, strategyRuns: changedRuns }) => {
      if (createdStrategy) center.setStrategies((current) => [createdStrategy, ...current]);
      if (updatedStrategies) center.setStrategies(updatedStrategies);
      if (deletedStrategyId !== undefined) center.setStrategies((current) => current.filter((monitor) => monitor.id !== deletedStrategyId));
      if (changedRuns) center.setStrategyRuns((current) => ({ ...current, ...changedRuns }));
    },
    onStockChanged: ({ createdStock, updatedStock, deletedStockId }) => {
      if (createdStock) center.setStocks((current) => [createdStock, ...current]);
      if (updatedStock) center.setStocks((current) => current.map((monitor) => monitor.id === updatedStock.id ? updatedStock : monitor));
      if (deletedStockId !== undefined) center.setStocks((current) => current.filter((monitor) => monitor.id !== deletedStockId));
    },
  });
  const saveStrategy = async () => {
    const saved = await saveStrategyAction({ name: strategyName, selectedStrategy, market: strategyMarket, frequency, symbols: strategySymbols });
    if (saved) { setStrategyName(''); setStrategySymbols(''); setShowStrategyForm(false); }
  };
  const saveStock = async () => {
    const saved = await saveStockAction({ market: stockMarket, symbol: stockSymbol, threshold });
    if (saved) { setStockMarket(''); setStockSymbol(''); setThreshold(''); setShowStockForm(false); }
  };
  const confirmAction = async () => { setPendingAction(null); await confirmMonitorAction(pendingAction); };

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-foreground">监控中心</h2>
          <p className="mt-1 text-xs text-muted-text">策略运行与价格触发各自独立管理</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => { void loadStrategies(); void loadStocks(); }} aria-label="刷新监控">
          <RiRefreshLine className="h-4 w-4" />刷新
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="策略监控" subtitle="STRATEGY RUNS" padding="md">
          <div className="mb-4 flex items-center justify-between">
            <p className="text-xs text-secondary-text">配置策略、市场、标的和执行频率</p>
            <Button size="sm" variant="secondary" onClick={() => setShowStrategyForm((value) => !value)}>
              <RiAddLine className="h-4 w-4" />添加策略监控
            </Button>
          </div>
          {strategyCatalogError ? <p role="alert" className="mb-3 text-xs text-danger">{strategyCatalogError}</p> : null}
          {strategyActionError ? <p role="alert" className="mb-3 text-xs text-danger">{strategyActionError}</p> : null}
          {createStrategyError ? <p role="alert" className="mb-3 text-xs text-danger">{createStrategyError}</p> : null}
          {showStrategyForm && (
            <div className="mb-4 grid gap-3 rounded-xl border border-border/50 bg-card/30 p-4 md:grid-cols-2">
              <Select label="策略名称" value={strategyName} onChange={setStrategyName} disabled={strategyCatalogLoading || Boolean(strategyCatalogError)} placeholder={strategyCatalogLoading ? '加载策略目录…' : '请选择策略'} options={strategyCatalog.map((strategy) => ({ value: strategy.name, label: strategy.name }))} />
              <Select label="市场" value={strategyMarket} onChange={(value) => setStrategyMarket(value as MonitoringMarket)} options={marketOptions} />
              <Input label="标的（逗号分隔）" value={strategySymbols} onChange={(event) => setStrategySymbols(event.target.value)} placeholder="可选，如 600000,000001" />
              <Select label="频率" value={frequency} onChange={(value) => setFrequency(value as MonitoringFrequency)} options={frequencyOptions} />
              <div className="flex gap-2 md:col-span-2">
                <Button size="sm" onClick={() => void saveStrategy()} isLoading={saving} disabled={strategyCatalogLoading || Boolean(strategyCatalogError) || !selectedStrategy}>保存策略监控</Button>
                <Button size="sm" variant="ghost" onClick={() => setShowStrategyForm(false)}>取消</Button>
              </div>
            </div>
          )}
          {strategyLoading ? <p className="py-8 text-center text-sm text-muted-text">加载策略监控…</p> : loadStrategyError ? <p role="alert" className="py-8 text-center text-sm text-danger">{loadStrategyError}</p> : strategies.length === 0 ? <p className="py-8 text-center text-sm text-muted-text">暂无策略监控</p> : (
            <div className="space-y-3">
              {strategies.map((monitor) => (
                <div key={monitor.id} className="rounded-xl border border-border/50 bg-card/30 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2"><span className="font-medium text-foreground">{monitor.name}</span><Badge variant={monitor.is_active ? 'success' : 'default'}>{monitor.is_active ? '已启用' : '已停用'}</Badge><span className="text-xs text-secondary-text">最近运行：{statusLabel(monitor.last_run_status)}</span></div>
                      <p className="mt-1 text-xs text-secondary-text">{marketLabel(monitor.market)} · {monitor.frequency} · {monitor.symbols?.join(', ') || '全市场'}</p>
                    </div>
                    <Button size="xsm" variant="danger-subtle" aria-label={`删除策略 ${monitor.name}`} onClick={() => setPendingAction({ kind: 'delete-strategy', id: monitor.id, label: monitor.name })}><RiDeleteBinLine className="h-4 w-4" /></Button>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-secondary-text"><span>下次运行：{monitor.next_run_date || '待调度'}</span><span>最近状态：{statusLabel(monitor.last_run_status)}</span></div>
                  <div className="mt-3 flex items-center justify-between border-t border-border/30 pt-3"><span className="text-xs text-muted-text">历史运行 {strategyRuns[monitor.id]?.length ?? 0} 次</span><Button size="xsm" variant="outline" isLoading={runningStrategyId === monitor.id} onClick={() => void runStrategy(monitor.id)}><RiPlayLine className="h-3.5 w-3.5" />立即运行</Button></div>
                  {(strategyRuns[monitor.id]?.length ?? 0) > 0 && <div className="mt-3 rounded-lg bg-background/30 p-3"><p className="mb-2 text-xs font-medium text-secondary-text">运行历史</p>{strategyRuns[monitor.id].map((run) => <div key={run.id} className="flex justify-between text-xs text-muted-text"><span>{run.scheduled_date}</span><span>{statusLabel(run.status)}</span></div>)}</div>}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="股票价格监控" subtitle="PRICE EVENTS" padding="md">
          <div className="mb-4 flex items-center justify-between"><p className="text-xs text-secondary-text">手动设置市场、股票代码和价格阈值</p><Button size="sm" variant="secondary" onClick={() => setShowStockForm((value) => !value)}><RiAddLine className="h-4 w-4" />添加股票监控</Button></div>
          {showStockForm && <div className="mb-4 grid gap-3 rounded-xl border border-border/50 bg-card/30 p-4 md:grid-cols-3"><Select label="市场" value={stockMarket} onChange={setStockMarket} options={[{ value: '', label: '请选择市场' }, ...marketOptions]} /><Input label="股票代码" value={stockSymbol} error={stockFormErrors.symbol} onChange={(event) => setStockSymbol(event.target.value)} placeholder="如 600000" /><Input label="阈值价格" type="number" min="0" step="any" value={threshold} error={stockFormErrors.threshold} onChange={(event) => setThreshold(event.target.value)} placeholder="必须大于 0" /><div className="md:col-span-3">{stockFormErrors.market ? <p role="alert" className="mb-2 text-xs text-danger">{stockFormErrors.market}</p> : null}<div className="flex gap-2"><Button size="sm" onClick={() => void saveStock()} isLoading={saving}>保存股票监控</Button><Button size="sm" variant="ghost" onClick={() => setShowStockForm(false)}>取消</Button></div></div></div>}
           {stockActionError ? <p role="alert" className="mb-3 text-xs text-danger">{stockActionError}</p> : null}
          {stockLoading ? <p className="py-8 text-center text-sm text-muted-text">加载股票监控…</p> : stockError ? <p role="alert" className="py-8 text-center text-sm text-danger">{stockError}</p> : stocks.length === 0 ? <p className="py-8 text-center text-sm text-muted-text">暂无股票价格监控</p> : <div className="space-y-3">{stocks.map((monitor) => <div key={monitor.id} className="rounded-xl border border-border/50 bg-card/30 p-4"><div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="font-mono font-medium text-foreground">{monitor.symbol}</span><Badge variant={monitor.state === 'triggered' ? 'danger' : monitor.state === 'paused' ? 'warning' : 'success'}>{stateLabel(monitor.state)}</Badge></div><p className="mt-1 text-xs text-secondary-text">{marketLabel(monitor.market)}{monitor.name ? ` · ${monitor.name}` : ''}</p></div><Button size="xsm" variant="danger-subtle" aria-label={`删除股票 ${monitor.symbol}`} onClick={() => setPendingAction({ kind: 'delete-stock', id: monitor.id, label: monitor.symbol })}><RiDeleteBinLine className="h-4 w-4" /></Button></div><div className="mt-3 grid grid-cols-2 gap-2 text-xs text-secondary-text"><span>当前价 {monitor.last_price ?? '暂无'}</span><span>阈值 {monitor.threshold_price}</span><span>事件 {stockEvents[monitor.id]?.length ?? 0} 次</span><span>状态 {monitor.is_active ? '有效' : '已删除'}</span></div>{(stockEvents[monitor.id]?.length ?? 0) > 0 && <div className="mt-3 rounded-lg bg-background/30 p-3"><p className="mb-2 text-xs font-medium text-secondary-text">价格事件</p>{stockEvents[monitor.id].map((event) => <div key={event.id} className="flex justify-between text-xs text-muted-text"><span>{event.observed_date}</span><span>{event.observed_price}</span></div>)}</div>}<div className="mt-3 flex justify-end gap-2 border-t border-border/30 pt-3">{monitor.state === 'paused' ? <Button size="xsm" variant="outline" aria-label={`恢复 ${monitor.symbol}`} onClick={() => setPendingAction({ kind: 'resume', monitor })}><RiPlayLine className="h-3.5 w-3.5" />恢复</Button> : <Button size="xsm" variant="ghost" aria-label={`暂停 ${monitor.symbol}`} onClick={() => setPendingAction({ kind: 'pause', monitor })}><RiPauseLine className="h-3.5 w-3.5" />暂停</Button>}</div></div>)}</div>}
        </Card>
      </div>

      <ConfirmDialog isOpen={pendingAction !== null} title={pendingAction?.kind.startsWith('delete') ? '确认删除监控' : '确认变更监控状态'} message={pendingAction?.kind.startsWith('delete') ? `将删除“${pendingAction.label}”，历史记录会保留但监控不再生效。` : `确认${pendingAction?.kind === 'pause' ? '暂停' : '恢复'}该股票价格监控吗？`} confirmText="确认" isDanger={pendingAction?.kind.startsWith('delete')} onConfirm={() => void confirmAction()} onCancel={() => setPendingAction(null)} />
    </div>
  );
};

export default MarketMonitor;
