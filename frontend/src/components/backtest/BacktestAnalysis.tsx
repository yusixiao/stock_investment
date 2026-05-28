import type React from 'react';
import { useState, useCallback, useEffect } from 'react';
import { cn } from '../../utils/cn';
import BacktestConfig from './BacktestConfig';
import BacktestResult from './BacktestResult';
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

  // 数据缓存状态:仅用于 BacktestConfig 判断是否允许运行(加载弹窗已迁移到全局浮动条)
  const [cacheStatus, setCacheStatus] = useState<CacheStatusMap | null>(null);

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
        {/* 数据缓存加载入口已迁移到全局左下角浮动条(DataCacheStatusBar) */}
      </div>

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
