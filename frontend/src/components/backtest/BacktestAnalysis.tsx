import type React from 'react';
import { useState, useCallback } from 'react';
import { cn } from '../../utils/cn';
import BacktestConfig from './BacktestConfig';
import BacktestResult from './BacktestResult';
import BacktestHistory from './BacktestHistory';
import BacktestDetail from './BacktestDetail';

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

type ViewTab = 'single' | 'market' | 'history';

const TABS: { key: ViewTab; label: string }[] = [
  { key: 'single', label: '个股回测' },
  { key: 'market', label: '全市场回测' },
  { key: 'history', label: '历史记录' },
];

const BacktestAnalysis: React.FC = () => {
  const [view, setView] = useState<ViewTab>('single');
  const [currentTask, setCurrentTask] = useState<BacktestTask | null>(null);
  // 历史详情态:不为 null 时进入只读详情视图(左侧参数+ID,右侧复用 BacktestResult)
  const [detailTask, setDetailTask] = useState<BacktestTask | null>(null);

  const handleRunBacktest = (task: BacktestTask) => {
    setCurrentTask(task);
    setDetailTask(null);
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

  const handleViewHistory = (task: BacktestTask) => {
    // 在历史记录页内点击行 → 进入详情(详情视图叠在历史 tab 上)
    setDetailTask(task);
  };

  const handleBackFromDetail = () => {
    setDetailTask(null);
  };

  // 切 tab 时清掉详情态,保证 tab 行为一致(点哪个 tab 就立刻显示对应内容)
  const handleSelectTab = (next: ViewTab) => {
    setDetailTask(null);
    setView(next);
  };

  const mode: BacktestMode = view === 'market' ? 'market' : 'single';

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-shrink-0 border-b border-border/30 bg-card/30 px-4 py-2">
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
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {view === 'history' ? (
          detailTask ? (
            <BacktestDetail task={detailTask} onBack={handleBackFromDetail} />
          ) : (
            <BacktestHistory onSelect={handleViewHistory} />
          )
        ) : (
          <>
            <aside className="w-80 flex-shrink-0 overflow-y-auto border-r border-border/30 bg-card/20">
              <BacktestConfig mode={mode} onRun={handleRunBacktest} onTaskUpdate={handleTaskUpdate} />
            </aside>
            <main className="min-h-0 flex-1 overflow-y-auto">
              <BacktestResult task={currentTask} />
            </main>
          </>
        )}
      </div>
    </div>
  );
};

export default BacktestAnalysis;
