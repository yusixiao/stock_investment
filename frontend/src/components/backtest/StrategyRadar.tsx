import type React from 'react';
import { useEffect, useMemo, useState } from 'react';
import { RiSearchLine } from '@remixicon/react';
import { cn } from '../../utils/cn';
import { backtestEngineApi, type StrategyInfo } from '../../api/backtestEngine';

// 时间范围:扫描时回看的历史窗口长度(用于策略计算所需的历史数据切片)
type LookbackKey = '1m' | '1y' | '3y' | '5y';

const LOOKBACK_OPTIONS: { value: LookbackKey; label: string }[] = [
  { value: '1m', label: '一个月' },
  { value: '1y', label: '一年' },
  { value: '3y', label: '三年' },
  { value: '5y', label: '五年' },
];

interface ScanConfig {
  strategyClass: string;
  market: string;
  lookback: LookbackKey;
}

// 选股结果项:每只命中股票一行
interface ScanResultItem {
  symbol: string;
  name: string;
  currentPrice: number;
  changePct: number; // 当日涨跌幅(0.0123 = +1.23%)
  signalDate: string; // 命中信号日期 YYYY-MM-DD
  // 关键因子值:键名按策略而定(PE/PB/ROE/MA缠绕度/连续分红年数 等)
  factors: Record<string, number | string>;
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
  const [results, setResults] = useState<ScanResultItem[]>([]);
  const [scanDone, setScanDone] = useState(false);
  const [scannedTotal, setScannedTotal] = useState(0);

  // 拉真实策略列表(与 BacktestConfig 共用同一来源)
  useEffect(() => {
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
  }, []);

  const selectedStrategy = useMemo(
    () => strategies.find((s) => s.className === config.strategyClass),
    [strategies, config.strategyClass],
  );

  const handleScan = () => {
    if (!config.strategyClass) return;
    setIsScanning(true);
    setScanDone(false);
    // TODO: 接后端「全市场选股」API。当前为前端 mock 占位:
    //   计划路由 POST /api/screener/run-market,入参 {strategy_class,filepath,
    //   params,market,lookback},返回 {total_scanned,hits:[{symbol,name,
    //   current_price,change_pct,signal_date,factors}]}
    setTimeout(() => {
      setResults([]);
      setScannedTotal(0);
      setIsScanning(false);
      setScanDone(true);
    }, 1200);
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
              <option value="US">美股</option>
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-secondary-text">时间范围</label>
            <select
              value={config.lookback}
              onChange={(e) =>
                setConfig({ ...config, lookback: e.target.value as LookbackKey })
              }
              className="input-surface input-focus-glow h-9 w-28 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
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
            disabled={isScanning || !config.strategyClass}
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

          {isScanning && (
            <span className="text-xs text-muted-text">正在扫描全市场...</span>
          )}

          {scanDone && !isScanning && (
            <span className="text-xs text-muted-text">
              扫描了 {scannedTotal.toLocaleString()} 只股票,命中 {results.length} 只
            </span>
          )}
        </div>

        {selectedStrategy?.frequency && (
          <div className="mt-2 text-xs text-muted-text">
            策略频率:{selectedStrategy.frequency} · 时间范围决定回看历史数据的长度,用于因子计算
          </div>
        )}
      </div>

      {/* Results */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {!scanDone && results.length === 0 && !isScanning && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border border-dashed border-border/60 bg-card/30">
                <RiSearchLine className="h-7 w-7 text-secondary-text" />
              </div>
              <p className="text-sm text-secondary-text">选择策略后开始扫描</p>
              <p className="mt-1 text-xs text-muted-text">
                策略雷达会扫描全市场股票,列出当前命中策略条件的标的
              </p>
            </div>
          </div>
        )}

        {scanDone && results.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-secondary-text">暂无命中股票</p>
              <p className="mt-1 text-xs text-muted-text">
                当前时间范围内没有满足策略条件的股票,可尝试调整参数或切换市场
              </p>
            </div>
          </div>
        )}

        {results.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2 text-right">当前价</th>
                  <th className="px-3 py-2 text-right">涨跌幅</th>
                  <th className="px-3 py-2">命中信号日期</th>
                  <th className="px-3 py-2">关键因子值</th>
                </tr>
              </thead>
              <tbody>
                {results.map((item) => (
                  <tr
                    key={item.symbol}
                    className="border-b border-border/20 hover:bg-hover/30"
                  >
                    <td className="px-3 py-2 font-mono">{item.symbol}</td>
                    <td className="px-3 py-2">{item.name}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {item.currentPrice.toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        'px-3 py-2 text-right tabular-nums',
                        item.changePct >= 0 ? 'text-success' : 'text-danger',
                      )}
                    >
                      {item.changePct >= 0 ? '+' : ''}
                      {(item.changePct * 100).toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-secondary-text">
                      {item.signalDate}
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
                              {typeof v === 'number' ? v.toFixed(2) : v}
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
    </div>
  );
};

export default StrategyRadar;
