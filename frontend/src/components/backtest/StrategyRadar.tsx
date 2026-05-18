import type React from 'react';
import { useState } from 'react';
import { RiSearchLine } from '@remixicon/react';
import { cn } from '../../utils/cn';

interface ScanConfig {
  strategy: string;
  market: string;
  period: string;
}

interface ScanResultItem {
  rank: number;
  symbol: string;
  name: string;
  annReturn: number;
  maxDrawdown: number;
  sharpe: number;
  winRate: number;
  totalTrades: number;
  alpha: number;
}

const StrategyRadar: React.FC = () => {
  const [config, setConfig] = useState<ScanConfig>({
    strategy: '',
    market: 'A',
    period: 'daily',
  });
  const [isScanning, setIsScanning] = useState(false);
  const [results, setResults] = useState<ScanResultItem[]>([]);
  const [scanDone, setScanDone] = useState(false);

  const handleScan = () => {
    setIsScanning(true);
    setScanDone(false);
    setTimeout(() => {
      setResults([]);
      setIsScanning(false);
      setScanDone(true);
    }, 2000);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Config Bar */}
      <div className="flex-shrink-0 border-b border-border/30 bg-card/20 px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-secondary-text">策略</label>
            <select
              value={config.strategy}
              onChange={(e) => setConfig({ ...config, strategy: e.target.value })}
              className="input-surface input-focus-glow h-9 w-48 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
            >
              <option value="">请选择策略</option>
              <option value="ma_cross">均线交叉</option>
              <option value="macd_divergence">MACD背离</option>
              <option value="rsi_oversold">RSI超卖反弹</option>
              <option value="breakout_60">60日突破</option>
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
            <label className="text-xs text-secondary-text">周期</label>
            <select
              value={config.period}
              onChange={(e) => setConfig({ ...config, period: e.target.value })}
              className="input-surface input-focus-glow h-9 w-24 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
            >
              <option value="daily">日线</option>
              <option value="weekly">周线</option>
              <option value="monthly">月线</option>
            </select>
          </div>

          <button
            type="button"
            onClick={handleScan}
            disabled={isScanning || !config.strategy}
            className="btn-primary flex h-9 items-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isScanning ? (
              <>
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
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
            <span className="text-xs text-muted-text">
              正在扫描全市场...
            </span>
          )}
        </div>
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
              <p className="mt-1 text-xs text-muted-text">策略雷达会扫描全市场股票，按回测表现排名</p>
            </div>
          </div>
        )}

        {scanDone && results.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-secondary-text">暂无扫描结果</p>
              <p className="mt-1 text-xs text-muted-text">未找到符合策略条件的股票</p>
            </div>
          </div>
        )}

        {results.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2 text-right">年化收益</th>
                  <th className="px-3 py-2 text-right">最大回撤</th>
                  <th className="px-3 py-2 text-right">夏普比</th>
                  <th className="px-3 py-2 text-right">胜率</th>
                  <th className="px-3 py-2 text-right">交易次数</th>
                  <th className="px-3 py-2 text-right">Alpha</th>
                </tr>
              </thead>
              <tbody>
                {results.map((item) => (
                  <tr key={item.symbol} className="border-b border-border/20 hover:bg-hover/30">
                    <td className="px-3 py-2 text-muted-text">{item.rank}</td>
                    <td className="px-3 py-2 font-mono">{item.symbol}</td>
                    <td className="px-3 py-2">{item.name}</td>
                    <td className={cn('px-3 py-2 text-right tabular-nums', item.annReturn >= 0 ? 'text-success' : 'text-danger')}>
                      {(item.annReturn * 100).toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-danger">
                      {(item.maxDrawdown * 100).toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{item.sharpe.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{(item.winRate * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right tabular-nums">{item.totalTrades}</td>
                    <td className={cn('px-3 py-2 text-right tabular-nums', item.alpha >= 0 ? 'text-success' : 'text-danger')}>
                      {item.alpha >= 0 ? '+' : ''}{(item.alpha * 100).toFixed(2)}%
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
