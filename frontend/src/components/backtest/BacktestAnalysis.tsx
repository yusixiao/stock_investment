import type React from 'react';
import { useState, useCallback, useEffect } from 'react';
import { cn } from '../../utils/cn';
import BacktestConfig from './BacktestConfig';
import BacktestResult from './BacktestResult';
import DataCacheModal from './DataCacheModal';
import { backtestCacheApi, type CacheStatusMap } from '../../api/backtestCache';

export type BacktestMode = 'single' | 'market';

export interface BacktestTask {
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  mode: BacktestMode;
  strategyName: string;
  symbol?: string;
  market?: string;
  period: string;
  startDate: string;
  endDate: string;
  capital: number;
  commission: number;
  progress?: number;
  progressPhase?: string;
  result?: BacktestResultData | null;
  error?: string;
  createdAt: string;
  // 详情视图用:策略原始参数(pipeline_info.params),仅展示用
  params?: Record<string, unknown>;
  // 任务类型(backtest / scan-radar / screener);影响详情视图的渲染
  taskType?: string;
  // scan-radar 任务的原始 payload,详情页直接复用展示
  radarPayload?: import('../../api/backtestEngine').ScanRadarPayload | null;
}

export interface BacktestResultData {
  totalReturn: number;
  annualizedReturn: number;
  maxDrawdown: number;
  sharpeRatio: number;
  winRate: number;
  totalTrades: number;
  profitFactor: number;
  avgWin: number;
  avgLoss: number;
  equityCurve: { date: string; value: number }[];
  trades: TradeRecord[];
  rawBuys: BuyRecord[];
  endPrices: Record<string, number>;
}

export interface BuyRecord {
  date: string;
  symbol: string;
  price: number;
  shares: number;
}

export interface TradeRecord {
  entryDate: string;
  exitDate: string;
  symbol: string;
  direction: 'long' | 'short';
  entryPrice: number;
  exitPrice: number;
  quantity: number;
  pnl: number;
  pnlPct: number;
  holdDays: number;
}

type ViewTab = 'single' | 'market';

const TABS: { key: ViewTab; label: string }[] = [
  { key: 'single', label: '个股回测' },
  { key: 'market', label: '全市场回测' },
];

const BacktestAnalysis: React.FC = () => {
  const [view, setView] = useState<ViewTab>('single');
  const [currentTask, setCurrentTask] = useState<BacktestTask | null>(null);

  // 数据缓存:状态条 + 加载弹窗
  const [cacheStatus, setCacheStatus] = useState<CacheStatusMap | null>(null);
  const [cacheModalOpen, setCacheModalOpen] = useState(false);

  const refreshStatus = useCallback(() => {
    backtestCacheApi.status().then(setCacheStatus).catch(() => {});
  }, []);

  // 首次加载 + 任一市场 loading 时每 2s 轮询
  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (!cacheStatus) return;
    const anyLoading = Object.values(cacheStatus).some((s) => s.status === 'loading');
    if (!anyLoading) return;
    const t = setInterval(refreshStatus, 2000);
    return () => clearInterval(t);
  }, [cacheStatus, refreshStatus]);

  const handleRunBacktest = (task: BacktestTask) => {
    setCurrentTask(task);
  };

  const handleTaskUpdate = useCallback((taskId: string, updates: Partial<BacktestTask>) => {
    setCurrentTask(prev => {
      if (!prev) return prev;
      if (prev.taskId === taskId || updates.taskId) {
        return { ...prev, ...updates };
      }
      return prev;
    });
  }, []);

  const handleSelectTab = (next: ViewTab) => {
    setView(next);
  };

  const mode: BacktestMode = view === 'market' ? 'market' : 'single';

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-border/30 bg-card/30 px-4 py-2">
        <div className="inline-flex rounded-lg border border-border/50 bg-elevated/50 p-0.5">
          {TABS.map(tab => (
            <button
              key={tab.key}
              type="button"
              onClick={() => handleSelectTab(tab.key)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-all',
                view === tab.key
                  ? 'bg-cyan text-slate-950 shadow-sm'
                  : 'text-secondary-text hover:text-foreground',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => {
            refreshStatus();
            setCacheModalOpen(true);
          }}
          className="rounded-md border border-border/50 bg-elevated/50 px-3 py-1.5 text-xs font-medium text-secondary-text transition-colors hover:text-foreground"
        >
          加载数据
        </button>

        <div className="ml-auto flex items-center gap-3 text-xs">
          {(['A', 'HK', 'US'] as const).map((m) => {
            const s = cacheStatus?.[m];
            const label = m === 'A' ? 'A' : m === 'HK' ? 'H' : 'US';
            const text = s?.status === 'loaded'
              ? `已加载 ${s.symbols}`
              : s?.status === 'loading'
                ? '加载中…'
                : s?.status === 'failed'
                  ? '失败'
                  : '未加载';
            const color = s?.status === 'loaded'
              ? 'text-emerald-400'
              : s?.status === 'loading'
                ? 'text-amber-400'
                : s?.status === 'failed'
                  ? 'text-rose-400'
                  : 'text-muted-text';
            return (
              <span key={m} className="tabular-nums">
                <span className="text-secondary-text">{label}</span>
                <span className={`ml-1 ${color}`}>{text}</span>
              </span>
            );
          })}
        </div>
      </div>

      <DataCacheModal
        isOpen={cacheModalOpen}
        status={cacheStatus}
        onClose={() => setCacheModalOpen(false)}
        onRefresh={refreshStatus}
      />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-80 flex-shrink-0 overflow-y-auto border-r border-border/30 bg-card/20">
          <BacktestConfig
            mode={mode}
            onRun={handleRunBacktest}
            onTaskUpdate={handleTaskUpdate}
            cacheStatus={cacheStatus}
          />
        </aside>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <BacktestResult task={currentTask} />
        </main>
      </div>
    </div>
  );
};

export default BacktestAnalysis;
