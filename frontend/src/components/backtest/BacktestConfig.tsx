import type React from 'react';
import { useState, useEffect } from 'react';
import { RiPlayFill } from '@remixicon/react';
import { backtestEngineApi } from '../../api/backtestEngine';
import type { StrategyInfo } from '../../api/backtestEngine';
import type { BacktestMode, BacktestTask } from './BacktestAnalysis';
import { mapPayloadToResultData } from '../../utils/backtestPayload';
import type { CacheStatusMap } from '../../api/backtestCache';

interface Props {
  mode: BacktestMode;
  onRun: (task: BacktestTask) => void;
  onTaskUpdate: (taskId: string, updates: Partial<BacktestTask>) => void;
  cacheStatus: CacheStatusMap | null;
}

const BacktestConfig: React.FC<Props> = ({ mode, onRun, onTaskUpdate, cacheStatus }) => {
  const [symbol, setSymbol] = useState('');
  const [market, setMarket] = useState<'A' | 'HK' | 'US'>('A');
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
    // 频率锁定的策略,同步 period 到策略自身频率
    if (selectedStrategy && !selectedStrategy.frequencyOverridable && selectedStrategy.frequency) {
      setPeriod(selectedStrategy.frequency);
    }
  }, [selectedStrategy?.className]);

  // 单股模式固定走 A,全市场模式跟随 market 选择
  const targetMarket = mode === 'market' ? market : 'A';
  const targetCache = cacheStatus?.[targetMarket];
  const isCacheReady = targetCache?.loaded === true;
  const cacheHint = !cacheStatus
    ? null
    : targetCache?.status === 'loading'
      ? `${targetMarket} 数据加载中…`
      : isCacheReady
        ? null
        : `${targetMarket} 数据未加载,请点击顶部「加载数据」按钮先加载`;

  const handleRun = async () => {
    if (!selectedStrategy) return;
    if (!isCacheReady) return;
    setIsRunning(true);

    const taskId = crypto.randomUUID().slice(0, 8);
    const task: BacktestTask = {
      taskId,
      status: 'running',
      mode,
      strategyName: selectedStrategy.name,
      symbol: mode === 'single' ? symbol : undefined,
      market: mode === 'market' ? market : 'A',
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
        strategy_class: selectedStrategy.className,
        filepath: selectedStrategy.filepath,
        params: hasOverrides ? (paramValues as Record<string, unknown>) : undefined,
        frequency_override: selectedStrategy.frequencyOverridable ? period : undefined,
        start_date: startDate,
        end_date: endDate,
        symbols,
        market: mode === 'market' ? market : 'A',
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
              const mapped = payload ? mapPayloadToResultData(payload) : null;
              if (mapped) {
                onTaskUpdate(realTaskId, {
                  status: 'completed',
                  progress: 100,
                  result: mapped,
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

      {mode === 'single' ? (
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
      ) : (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-secondary-text">市场</label>
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value as 'A' | 'HK' | 'US')}
            className="input-surface input-focus-glow h-9 w-full appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
          >
            <option value="A">A 股</option>
            <option value="HK">港股</option>
            <option value="US">美股</option>
          </select>
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
          {strategies.map((s) => {
            const freqLabel = s.frequency === 'daily' ? '日线'
              : s.frequency === 'weekly' ? '周线'
              : s.frequency === 'monthly' ? '月线'
              : s.frequency || '';
            return (
              <option key={s.className} value={s.className}>
                {s.name}{freqLabel ? ` · ${freqLabel}` : ''}
              </option>
            );
          })}
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
        {selectedStrategy && !selectedStrategy.frequencyOverridable ? (
          <div
            className="input-surface flex h-9 w-full items-center rounded-lg border bg-transparent px-3 text-sm text-secondary-text"
            title="该策略的频率不可修改"
          >
            {selectedStrategy.frequency === 'daily' ? '日线'
              : selectedStrategy.frequency === 'weekly' ? '周线'
              : selectedStrategy.frequency === 'monthly' ? '月线'
              : (selectedStrategy.frequency || '日线')}
            <span className="ml-2 text-xs text-muted-text">(策略锁定)</span>
          </div>
        ) : (
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="input-surface input-focus-glow h-9 w-full appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
          >
            <option value="daily">日线</option>
            <option value="weekly">周线</option>
            <option value="monthly">月线</option>
          </select>
        )}
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

      {cacheHint && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          {cacheHint}
        </div>
      )}

      <button
        type="button"
        onClick={handleRun}
        disabled={isRunning || !strategy || !isCacheReady}
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
