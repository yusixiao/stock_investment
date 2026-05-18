import type React from 'react';
import { useState, useEffect } from 'react';
import { RiPlayFill } from '@remixicon/react';
import { backtestEngineApi } from '../../api/backtestEngine';
import type { StrategyInfo } from '../../api/backtestEngine';
import type { BacktestMode, BacktestTask } from './BacktestAnalysis';

interface Props {
  mode: BacktestMode;
  onRun: (task: BacktestTask) => void;
  onTaskUpdate: (taskId: string, updates: Partial<BacktestTask>) => void;
}

const BacktestConfig: React.FC<Props> = ({ mode, onRun, onTaskUpdate }) => {
  const [symbol, setSymbol] = useState('');
  const [strategy, setStrategy] = useState('');
  const [period, setPeriod] = useState('daily');
  const [startDate, setStartDate] = useState('2023-01-01');
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [capital, setCapital] = useState(100000);
  const [commission, setCommission] = useState(0.15);
  const [isRunning, setIsRunning] = useState(false);

  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [loadingStrategies, setLoadingStrategies] = useState(true);
  const [paramValues, setParamValues] = useState<Record<string, unknown>>({});

  useEffect(() => {
    backtestEngineApi.listStrategies()
      .then(setStrategies)
      .catch(() => setStrategies([]))
      .finally(() => setLoadingStrategies(false));
  }, []);

  const selectedStrategy = strategies.find(s => s.className === strategy);

  useEffect(() => {
    if (selectedStrategy?.params) {
      const defaults: Record<string, unknown> = {};
      for (const [key, def] of Object.entries(selectedStrategy.params)) {
        defaults[key] = def.default;
      }
      setParamValues(defaults);
    } else {
      setParamValues({});
    }
  }, [selectedStrategy?.className]);

  const handleRun = async () => {
    if (!selectedStrategy) return;
    setIsRunning(true);

    const taskId = crypto.randomUUID().slice(0, 8);
    const task: BacktestTask = {
      taskId,
      status: 'running',
      mode,
      strategyName: selectedStrategy.name,
      symbol: mode === 'single' ? symbol : undefined,
      market: 'A',
      period,
      startDate,
      endDate,
      capital,
      commission,
      progress: 0,
      result: null,
      createdAt: new Date().toISOString(),
    };
    onRun(task);

    try {
      const symbols = mode === 'single' && symbol
        ? [symbol.includes('.') ? symbol : `${symbol}.SZ`]
        : undefined;

      const hasOverrides = Object.keys(paramValues).length > 0;
      const resp = await backtestEngineApi.runBacktest({
        pipeline: [{ filepath: selectedStrategy.filepath, class_name: selectedStrategy.className }],
        start_date: startDate,
        end_date: endDate,
        symbols,
        param_overrides: hasOverrides ? { [selectedStrategy.className]: paramValues as Record<string, unknown> } : undefined,
      });

      const realTaskId = resp.task_id;
      onTaskUpdate(taskId, { taskId: realTaskId });

      const pollInterval = setInterval(async () => {
        try {
          const status = await backtestEngineApi.getStatus(realTaskId);
          if (status.status === 'running') {
            const progress = status.progress;
            if (progress && progress.total > 0) {
              const pct = Math.round((progress.current / progress.total) * 100);
              onTaskUpdate(realTaskId, { progress: pct, progressPhase: progress.phase });
            }
          } else {
            clearInterval(pollInterval);
            if (status.status === 'success') {
              const result = await backtestEngineApi.getResult(realTaskId);
              const payload = result.result;
              if (payload?.metrics) {
                onTaskUpdate(realTaskId, {
                  status: 'completed',
                  progress: 100,
                  result: {
                    totalReturn: payload.metrics.total_return,
                    annualizedReturn: payload.metrics.annualized_return,
                    maxDrawdown: payload.metrics.max_drawdown,
                    sharpeRatio: payload.metrics.sharpe_ratio,
                    winRate: payload.metrics.win_rate,
                    totalTrades: payload.metrics.total_trades,
                    profitFactor: payload.metrics.profit_factor,
                    avgWin: payload.metrics.avg_win,
                    avgLoss: payload.metrics.avg_loss,
                    equityCurve: payload.equity_curve || [],
                    trades: (payload.trades || []).map(t => ({
                      entryDate: t.entry_date,
                      exitDate: t.exit_date,
                      symbol: t.symbol,
                      direction: t.direction as 'long' | 'short',
                      entryPrice: t.entry_price,
                      exitPrice: t.exit_price,
                      quantity: t.shares,
                      pnl: t.pnl,
                      pnlPct: t.pnl_pct,
                      holdDays: t.hold_days,
                    })),
                  },
                });
              } else {
                onTaskUpdate(realTaskId, { status: 'completed', progress: 100 });
              }
            } else {
              onTaskUpdate(realTaskId, { status: 'failed', error: 'Backtest failed' });
            }
            setIsRunning(false);
          }
        } catch {
          clearInterval(pollInterval);
          onTaskUpdate(realTaskId, { status: 'failed', error: '轮询状态失败' });
          setIsRunning(false);
        }
      }, 1500);
    } catch (err) {
      onTaskUpdate(taskId, { status: 'failed', error: String(err) });
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-secondary-text">
        回测配置
      </div>

      {mode === 'single' && (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-secondary-text">股票代码</label>
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="如 000001.SZ 或 600519.SH"
            className="input-surface input-focus-glow h-9 w-full rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
          />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <label className="text-xs text-secondary-text">策略</label>
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          disabled={loadingStrategies}
          className="input-surface input-focus-glow h-9 w-full appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
        >
          <option value="">{loadingStrategies ? '加载中...' : '请选择策略'}</option>
          {strategies.map((s) => (
            <option key={s.className} value={s.className}>
              {s.name} ({s.strategyType === 'screener' ? '选股' : '交易'}{s.frequency ? ` · ${s.frequency}` : ''})
            </option>
          ))}
        </select>
      </div>

      {selectedStrategy?.params && Object.keys(selectedStrategy.params).length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-border/40 bg-card/30 p-3">
          <div className="text-xs font-medium text-secondary-text">策略参数</div>
          {Object.entries(selectedStrategy.params).map(([key, def]) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-xs text-muted-text" title={def.description || key}>
                {def.description || key}
              </label>
              {typeof def.default === 'boolean' ? (
                <label className="inline-flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(paramValues[key] ?? def.default)}
                    onChange={(e) => setParamValues(prev => ({ ...prev, [key]: e.target.checked }))}
                    className="h-4 w-4 rounded border-border accent-cyan"
                  />
                  <span className="text-xs text-foreground">{paramValues[key] ? '是' : '否'}</span>
                </label>
              ) : typeof def.default === 'number' ? (
                <input
                  type="number"
                  step="any"
                  value={paramValues[key] as number ?? def.default}
                  onChange={(e) => setParamValues(prev => ({ ...prev, [key]: Number(e.target.value) }))}
                  className="input-surface input-focus-glow h-8 w-full rounded-md border bg-transparent px-2 text-xs tabular-nums transition-all focus:outline-none"
                />
              ) : (
                <input
                  type="text"
                  value={String(paramValues[key] ?? def.default ?? '')}
                  onChange={(e) => setParamValues(prev => ({ ...prev, [key]: e.target.value }))}
                  className="input-surface input-focus-glow h-8 w-full rounded-md border bg-transparent px-2 text-xs transition-all focus:outline-none"
                />
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <label className="text-xs text-secondary-text">K线周期</label>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="input-surface input-focus-glow h-9 w-full appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
        >
          <option value="daily">日线</option>
          <option value="weekly">周线</option>
          <option value="monthly">月线</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-secondary-text">开始日期</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="input-surface input-focus-glow h-9 w-full rounded-lg border bg-transparent px-2 text-xs transition-all focus:outline-none"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-secondary-text">结束日期</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="input-surface input-focus-glow h-9 w-full rounded-lg border bg-transparent px-2 text-xs transition-all focus:outline-none"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-secondary-text">初始资金</label>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="input-surface input-focus-glow h-9 w-full rounded-lg border bg-transparent px-3 text-sm tabular-nums transition-all focus:outline-none"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-secondary-text">手续费%</label>
          <input
            type="number"
            step="0.01"
            value={commission}
            onChange={(e) => setCommission(Number(e.target.value))}
            className="input-surface input-focus-glow h-9 w-full rounded-lg border bg-transparent px-3 text-sm tabular-nums transition-all focus:outline-none"
          />
        </div>
      </div>

      <button
        type="button"
        onClick={handleRun}
        disabled={isRunning || !strategy}
        className="btn-primary mt-2 flex w-full items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isRunning ? (
          <>
            <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            回测中...
          </>
        ) : (
          <>
            <RiPlayFill className="h-4 w-4" />
            {mode === 'single' ? '回测个股' : '回测全市场'}
          </>
        )}
      </button>
    </div>
  );
};

export default BacktestConfig;
