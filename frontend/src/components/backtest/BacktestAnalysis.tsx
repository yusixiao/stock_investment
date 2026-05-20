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

const BacktestAnalysis: React.FC = () => {
  const [mode, setMode] = useState<BacktestMode>('single');
  const [currentTask, setCurrentTask] = useState<BacktestTask | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  // 历史详情态:不为 null 时进入只读详情视图(左侧参数+ID,右侧复用 BacktestResult)
  const [detailTask, setDetailTask] = useState<BacktestTask | null>(null);

  const handleRunBacktest = (task: BacktestTask) => {
    setCurrentTask(task);
    setShowHistory(false);
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
    setDetailTask(task);
    setShowHistory(false);
  };

  const handleBackFromDetail = () => {
    setDetailTask(null);
    setShowHistory(true);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex-shrink-0 border-b border-border/30 bg-card/30 px-4 py-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="inline-flex rounded-lg border border-border/50 bg-elevated/50 p-0.5">
              <button
                type="button"
                onClick={() => setMode('single')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-all',
                  mode === 'single'
                    ? 'bg-cyan text-slate-950 shadow-sm'
                    : 'text-secondary-text hover:text-foreground',
                )}
              >
                个股回测
              </button>
              <button
                type="button"
                onClick={() => setMode('market')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-all',
                  mode === 'market'
                    ? 'bg-cyan text-slate-950 shadow-sm'
                    : 'text-secondary-text hover:text-foreground',
                )}
              >
                全市场回测
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowHistory(!showHistory)}
            className={cn(
              'text-xs font-medium transition-colors',
              showHistory ? 'text-cyan' : 'text-secondary-text hover:text-foreground',
            )}
          >
            历史记录
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {detailTask ? (
          <BacktestDetail task={detailTask} onBack={handleBackFromDetail} />
        ) : showHistory ? (
          <BacktestHistory onSelect={handleViewHistory} />
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
