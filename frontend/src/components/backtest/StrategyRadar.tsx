import type React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { RiDownloadLine, RiSearchLine } from '@remixicon/react';
import { cn } from '../../utils/cn';
import {
  backtestEngineApi,
  type RadarLookback,
  type ScanRadarHit,
  type ScanRadarPayload,
  type StrategyInfo,
} from '../../api/backtestEngine';
import {
  buildRadarFilename,
  exportRadarHitsToXlsx,
} from '../../utils/exportRadarHitsXlsx';

// 时间范围:扫描时回看的窗口长度。yesterday 仅日频策略可用,其余跨周期策略支持。
const LOOKBACK_OPTIONS: { value: RadarLookback; label: string }[] = [
  { value: 'yesterday', label: '最新交易日' },
  { value: '1m', label: '一个月' },
  { value: '6m', label: '六个月' },
  { value: '1y', label: '一年' },
  { value: '3y', label: '三年' },
  { value: '5y', label: '五年' },
];

interface ScanConfig {
  strategyClass: string;
  market: string;
  lookback: RadarLookback;
}

const StrategyRadar: React.FC = () => {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategiesLoading, setStrategiesLoading] = useState(false);
  const [strategiesError, setStrategiesError] = useState<string | null>(null);

  const [config, setConfig] = useState<ScanConfig>({
    strategyClass: '',
    market: 'A',
    lookback: '1y',
  });
  const [isScanning, setIsScanning] = useState(false);
  const [scanPhase, setScanPhase] = useState<string>('');
  const [scanError, setScanError] = useState<string | null>(null);
  const [payload, setPayload] = useState<ScanRadarPayload | null>(null);
  const pollRef = useRef<number | null>(null);
  // 参数弹窗:点击「开始扫描」时若策略有可调参数则弹出,确认后才真正执行
  const [paramDialogOpen, setParamDialogOpen] = useState(false);
  const [paramValues, setParamValues] = useState<Record<string, unknown>>({});

  useEffect(() => {
    // 合法模式:挂载时拉取策略列表的数据获取 effect(先置 loading 再异步取数)。
    // React 对此无 effect 内替代写法,除非引入 React Query
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStrategiesLoading(true);
    backtestEngineApi
      .listStrategies()
      .then((list) => {
        setStrategies(list);
        setStrategiesError(null);
      })
      .catch((err: unknown) => {
        setStrategiesError(err instanceof Error ? err.message : '加载策略列表失败');
      })
      .finally(() => setStrategiesLoading(false));
    return () => {
      if (pollRef.current) window.clearTimeout(pollRef.current);
    };
  }, []);

  const selectedStrategy = useMemo(
    () => strategies.find((s) => s.className === config.strategyClass),
    [strategies, config.strategyClass],
  );

  // 频率冲突:策略 frequency != daily 且选「最新交易日」→ 禁用扫描
  const frequencyConflict = useMemo(() => {
    if (config.lookback !== 'yesterday') return false;
    const f = selectedStrategy?.frequency;
    return !!f && f !== 'daily';
  }, [selectedStrategy, config.lookback]);

  const pollResult = (taskId: string) => {
    backtestEngineApi
      .getStatus(taskId)
      .then((status) => {
        setScanPhase(status.progress?.phase ?? '');
        if (status.status === 'running') {
          pollRef.current = window.setTimeout(() => pollResult(taskId), 1000);
          return;
        }
        if (status.status === 'failed' || status.status === 'interrupted') {
          backtestEngineApi.getScanRadarResult(taskId).then((r) => {
            setScanError(r.error || (status.status === 'interrupted' ? '服务重启，任务中断' : '扫描失败'));
            setIsScanning(false);
          });
          return;
        }
        // success
        backtestEngineApi.getScanRadarResult(taskId).then((r) => {
          setPayload(r.result);
          setIsScanning(false);
          setScanPhase('');
        });
      })
      .catch((err: unknown) => {
        setScanError(err instanceof Error ? err.message : '轮询失败');
        setIsScanning(false);
      });
  };

  // 用 default 填充 paramValues(每次打开 dialog 重置)
  const openParamDialog = () => {
    if (!selectedStrategy) return;
    const defaults: Record<string, unknown> = {};
    if (selectedStrategy.params) {
      for (const [k, def] of Object.entries(selectedStrategy.params)) {
        defaults[k] = def.default;
      }
    }
    setParamValues(defaults);
    setParamDialogOpen(true);
  };

  const executeScan = (params: Record<string, unknown>) => {
    if (!selectedStrategy) return;
    setIsScanning(true);
    setScanError(null);
    setPayload(null);
    setScanPhase('提交任务...');
    backtestEngineApi
      .scanRadar({
        strategy_class: selectedStrategy.className,
        filepath: selectedStrategy.filepath,
        params,
        lookback: config.lookback,
        market: config.market,
      })
      .then((resp) => {
        pollResult(resp.task_id);
      })
      .catch((err: unknown) => {
        setScanError(err instanceof Error ? err.message : '提交失败');
        setIsScanning(false);
      });
  };

  // 入口:有可调参数 → 先弹窗;无参数 → 直接扫描
  const handleScan = () => {
    if (!config.strategyClass || !selectedStrategy || frequencyConflict) return;
    const hasParams =
      selectedStrategy.params &&
      Object.keys(selectedStrategy.params).length > 0;
    if (hasParams) {
      openParamDialog();
    } else {
      executeScan({});
    }
  };

  const handleConfirmDialog = () => {
    setParamDialogOpen(false);
    executeScan(paramValues);
  };

  const hits: ScanRadarHit[] = payload?.hits ?? [];

  const handleExport = () => {
    if (!payload || hits.length === 0) return;
    const filename = buildRadarFilename({
      strategyName: selectedStrategy?.name,
      market: config.market,
      startDate: payload.date_range?.start,
      endDate: payload.date_range?.end,
    });
    exportRadarHitsToXlsx(payload, filename);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Config Bar */}
      <div className="flex-shrink-0 border-b border-border/30 bg-card/20 px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-secondary-text">策略</label>
            <select
              value={config.strategyClass}
              onChange={(e) => setConfig({ ...config, strategyClass: e.target.value })}
              disabled={strategiesLoading || !!strategiesError}
              className="input-surface input-focus-glow h-9 w-56 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none disabled:opacity-50"
            >
              <option value="">
                {strategiesLoading
                  ? '加载策略中...'
                  : strategiesError
                  ? '加载失败'
                  : '请选择策略'}
              </option>
              {strategies.map((s) => (
                <option key={s.className} value={s.className}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-secondary-text">市场</label>
            <select
              value={config.market}
              onChange={(e) => setConfig({ ...config, market: e.target.value })}
              className="input-surface input-focus-glow h-9 w-28 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
            >
              <option value="A">A股</option>
              <option value="HK">港股</option>
              <option value="HK_CONNECT">港股通</option>
              <option value="US">美股</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-secondary-text">时间范围</label>
            <select
              value={config.lookback}
              onChange={(e) =>
                setConfig({ ...config, lookback: e.target.value as RadarLookback })
              }
              className="input-surface input-focus-glow h-9 w-32 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
            >
              {LOOKBACK_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            onClick={handleScan}
            disabled={isScanning || !config.strategyClass || frequencyConflict}
            className="btn-primary flex h-9 items-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isScanning ? (
              <>
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                扫描中...
              </>
            ) : (
              <>
                <RiSearchLine className="h-4 w-4" />
                开始扫描
              </>
            )}
          </button>

          {isScanning && scanPhase && (
            <span className="text-xs text-muted-text">{scanPhase}</span>
          )}

          {payload && !isScanning && (
            <span className="text-xs text-muted-text">
              扫描了 {payload.total_scanned.toLocaleString()} 只股票,命中 {hits.length} 只
              {payload.date_range && ` · 区间 ${payload.date_range.start} ~ ${payload.date_range.end}`}
              {payload.data_latest_date && ` · 实际数据日 ${payload.data_latest_date}`}
            </span>
          )}

          {payload && !isScanning && hits.length > 0 && (
            <button
              type="button"
              onClick={handleExport}
              aria-label="导出雷达命中到 Excel"
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border/60 bg-card/40 px-3 text-xs text-foreground transition-colors hover:bg-hover"
            >
              <RiDownloadLine className="h-3.5 w-3.5" />
              导出 Excel
            </button>
          )}
        </div>

        {frequencyConflict && (
          <div className="mt-2 text-xs text-danger">
            「最新交易日」仅适用于日频策略,当前策略频率为 {selectedStrategy?.frequency}
          </div>
        )}

        {!frequencyConflict && selectedStrategy?.frequency && (
          <div className="mt-2 text-xs text-muted-text">
            策略频率:{selectedStrategy.frequency} ·
            时间范围决定扫描窗口的长度,窗口内每根 bar 评估一次
          </div>
        )}

        {scanError && (
          <div className="mt-2 text-xs text-danger">{scanError}</div>
        )}
      </div>

      {/* Results */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!payload && !isScanning && !scanError && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border border-dashed border-border/60 bg-card/30">
                <RiSearchLine className="h-7 w-7 text-secondary-text" />
              </div>
              <p className="text-sm text-secondary-text">选择策略后开始扫描</p>
              <p className="mt-1 text-xs text-muted-text">
                策略雷达会扫描全市场股票,列出窗口内命中策略条件的标的
              </p>
            </div>
          </div>
        )}

        {payload && hits.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-secondary-text">暂无命中股票</p>
              <p className="mt-1 text-xs text-muted-text">
                当前时间范围内没有满足策略条件的股票,可尝试调整参数或切换市场
              </p>
            </div>
          </div>
        )}

        {hits.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2 text-right">当前价</th>
                  <th className="px-3 py-2 text-right">信号日至今</th>
                  <th className="px-3 py-2">最近命中日</th>
                  <th className="px-3 py-2 text-right">命中次数</th>
                  <th className="px-3 py-2">关键因子值</th>
                </tr>
              </thead>
              <tbody>
                {hits.map((item) => (
                  <tr
                    key={item.symbol}
                    className="border-b border-border/20 hover:bg-hover/30"
                  >
                    <td className="px-3 py-2 font-mono">{item.symbol}</td>
                    <td className="px-3 py-2">{item.name ?? '-'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {item.current_price.toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        'px-3 py-2 text-right tabular-nums',
                        item.change_pct_since_signal == null
                          ? 'text-muted-text'
                          : item.change_pct_since_signal >= 0
                          ? 'text-success'
                          : 'text-danger',
                      )}
                    >
                      {item.change_pct_since_signal == null
                        ? '-'
                        : `${item.change_pct_since_signal >= 0 ? '+' : ''}${(item.change_pct_since_signal * 100).toFixed(2)}%`}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-secondary-text">
                      {item.last_match_date}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {item.match_count}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(item.factors).map(([k, v]) => (
                          <span
                            key={k}
                            className="inline-flex items-center gap-1 rounded-md border border-border/40 bg-card/40 px-2 py-0.5 text-xs"
                          >
                            <span className="text-muted-text">{k}</span>
                            <span className="tabular-nums">
                              {typeof v === 'number' ? v.toFixed(2) : String(v ?? '-')}
                            </span>
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 参数弹窗:确认后才真正提交扫描 */}
      {paramDialogOpen && selectedStrategy?.params &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
            onClick={() => setParamDialogOpen(false)}
          >
            <div
              className="mx-4 w-full max-w-md rounded-xl border border-border/70 bg-elevated p-6 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="mb-1 text-lg font-medium text-foreground">
                {selectedStrategy.name} · 参数
              </h3>
              <p className="mb-4 text-xs text-muted-text">
                调整参数后点「开始扫描」执行,默认值为策略推荐值
              </p>

              <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto">
                {Object.entries(selectedStrategy.params).map(([key, def]) => (
                  <div key={key} className="flex flex-col gap-1">
                    <label
                      className="text-xs text-secondary-text"
                      title={def.description || key}
                    >
                      {def.description || key}
                    </label>
                    {typeof def.default === 'boolean' ? (
                      <label className="inline-flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={Boolean(paramValues[key] ?? def.default)}
                          onChange={(e) =>
                            setParamValues((prev) => ({
                              ...prev,
                              [key]: e.target.checked,
                            }))
                          }
                          className="h-4 w-4 rounded border-border accent-cyan"
                        />
                        <span className="text-xs text-foreground">
                          {paramValues[key] ? '是' : '否'}
                        </span>
                      </label>
                    ) : typeof def.default === 'number' ? (
                      <input
                        type="number"
                        step="any"
                        value={
                          (paramValues[key] as number | undefined) ??
                          (def.default as number)
                        }
                        onChange={(e) =>
                          setParamValues((prev) => ({
                            ...prev,
                            [key]: Number(e.target.value),
                          }))
                        }
                        className="input-surface input-focus-glow h-9 w-full rounded-md border bg-transparent px-3 text-sm tabular-nums transition-all focus:outline-none"
                      />
                    ) : (
                      <input
                        type="text"
                        value={String(
                          paramValues[key] ?? def.default ?? '',
                        )}
                        onChange={(e) =>
                          setParamValues((prev) => ({
                            ...prev,
                            [key]: e.target.value,
                          }))
                        }
                        className="input-surface input-focus-glow h-9 w-full rounded-md border bg-transparent px-3 text-sm transition-all focus:outline-none"
                      />
                    )}
                  </div>
                ))}
              </div>

              <div className="mt-6 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setParamDialogOpen(false)}
                  className="rounded-lg border border-border/70 px-4 py-2 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleConfirmDialog}
                  className="rounded-lg bg-cyan/80 px-4 py-2 text-sm font-medium text-foreground shadow-lg shadow-cyan/20 transition-colors hover:bg-cyan"
                >
                  开始扫描
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
};

export default StrategyRadar;
