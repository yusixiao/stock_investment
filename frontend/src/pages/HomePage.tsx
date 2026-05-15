import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { StockAutocomplete } from '../components/StockAutocomplete';
import { KlineChart, type KlineDataPoint } from '../components/KlineChart';
import apiClient from '../api';

type Period = 'daily' | 'weekly' | 'monthly';
type Adjust = 'raw' | 'qfq' | 'hfq';

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: 'daily', label: '日K' },
  { value: 'weekly', label: '周K' },
  { value: 'monthly', label: '月K' },
];

const ADJUST_OPTIONS: { value: Adjust; label: string }[] = [
  { value: 'raw', label: '不复权' },
  { value: 'qfq', label: '前复权' },
  { value: 'hfq', label: '后复权' },
];

const HomePage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [selectedCode, setSelectedCode] = useState('');
  const [selectedName, setSelectedName] = useState('');
  const [klineData, setKlineData] = useState<KlineDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState<Period>('daily');
  const [adjust, setAdjust] = useState<Adjust>('qfq');

  useEffect(() => {
    document.title = 'StockLab';
  }, []);

  const loadKline = useCallback(async (code: string, p: Period, a: Adjust) => {
    setLoading(true);
    setError('');
    try {
      const resp = await apiClient.get(`/api/market/${code}/kline`, {
        params: { period: p, adjust: a },
      });
      setKlineData(resp.data.data || []);
    } catch {
      setError(`加载 ${code} K线数据失败`);
      setKlineData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSearch = useCallback((stockCode?: string, name?: string) => {
    const code = stockCode || query.trim();
    if (!code) return;
    setSelectedCode(code);
    setSelectedName(name || code);
    loadKline(code, period, adjust);
  }, [query, loadKline, period, adjust]);

  useEffect(() => {
    if (selectedCode) {
      loadKline(selectedCode, period, adjust);
    }
  }, [period, adjust]);

  return (
    <div
      data-testid="home-dashboard"
      className="flex h-[calc(100vh-5rem)] w-full flex-col overflow-hidden sm:h-[calc(100vh-5.5rem)] lg:h-[calc(100vh-2rem)]"
    >
      <header className="flex min-w-0 flex-shrink-0 items-center overflow-hidden px-3 py-3 md:px-4 md:py-4">
        <div className="flex min-w-0 flex-1 flex-col gap-2.5 md:flex-row md:items-center">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <div className="relative min-w-0 flex-1">
              <StockAutocomplete
                value={query}
                onChange={setQuery}
                onSubmit={(stockCode, name) => {
                  handleSearch(stockCode, name);
                }}
                placeholder="输入股票代码或名称，如 600519、00700、AAPL"
                disabled={false}
              />
            </div>
          </div>
          <div className="flex min-w-0 flex-shrink-0 items-center gap-2.5">
            <button
              type="button"
              onClick={() => handleSearch()}
              disabled={!query}
              className="btn-primary flex h-10 flex-1 items-center justify-center gap-1.5 whitespace-nowrap md:flex-none"
            >
              搜索
            </button>
          </div>
        </div>
      </header>

      {selectedCode && (
        <div className="flex items-center gap-4 px-3 pb-2 md:px-4">
          <span className="text-sm font-medium text-primary-text">
            {selectedName} <span className="text-secondary-text">({selectedCode})</span>
          </span>

          <div className="flex items-center gap-1 rounded-lg border border-border/50 p-0.5">
            {PERIOD_OPTIONS.map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setPeriod(opt.value)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  period === opt.value
                    ? 'bg-cyan/15 text-cyan font-medium'
                    : 'text-secondary-text hover:text-primary-text'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1 rounded-lg border border-border/50 p-0.5">
            {ADJUST_OPTIONS.map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setAdjust(opt.value)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  adjust === opt.value
                    ? 'bg-cyan/15 text-cyan font-medium'
                    : 'text-secondary-text hover:text-primary-text'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0 px-3 pb-3 md:px-4 md:pb-4">
        {loading && (
          <div className="flex h-full items-center justify-center text-secondary-text">
            加载中...
          </div>
        )}
        {error && (
          <div className="flex h-full items-center justify-center text-danger">
            {error}
          </div>
        )}
        {!loading && !error && klineData.length > 0 && (
          <KlineChart data={klineData} className="h-full w-full rounded-xl overflow-hidden" />
        )}
        {!loading && !error && klineData.length === 0 && (
          <div className="flex h-full items-center justify-center text-secondary-text">
            请搜索并选择一只股票查看K线
          </div>
        )}
      </div>
    </div>
  );
};

export default HomePage;
