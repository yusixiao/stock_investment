import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { StockAutocomplete } from '../components/StockAutocomplete';

const HomePage: React.FC = () => {
  const [query, setQuery] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState('SSE:000001');
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = 'StockLab';
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = '';

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: selectedSymbol,
      interval: 'D',
      timezone: 'Asia/Shanghai',
      theme: document.documentElement.classList.contains('light') ? 'light' : 'dark',
      style: '1',
      locale: 'zh_CN',
      allow_symbol_change: true,
      support_host: 'https://www.tradingview.com',
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      calendar: false,
      studies: ['MASimple@tv-basicstudies'],
    });

    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    widget.style.height = '100%';
    widget.style.width = '100%';

    containerRef.current.appendChild(widget);
    containerRef.current.appendChild(script);
  }, [selectedSymbol]);

  const handleSearch = useCallback((stockCode?: string) => {
    const code = stockCode || query.trim();
    if (!code) return;

    let tvSymbol = '';
    if (/^\d{6}$/.test(code)) {
      if (code.startsWith('6')) {
        tvSymbol = `SSE:${code}`;
      } else {
        tvSymbol = `SZSE:${code}`;
      }
    } else if (/^\d{5}$/.test(code)) {
      tvSymbol = `HKEX:${code}`;
    } else if (/^[A-Z]+$/.test(code.toUpperCase())) {
      tvSymbol = `NASDAQ:${code.toUpperCase()}`;
    } else {
      tvSymbol = code;
    }

    setSelectedSymbol(tvSymbol);
  }, [query]);

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
                onSubmit={(stockCode) => {
                  handleSearch(stockCode);
                }}
                placeholder="输入股票代码或名称，如 600519、贵州茅台、AAPL"
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

      <div className="flex-1 min-h-0 px-3 pb-3 md:px-4 md:pb-4">
        <div
          ref={containerRef}
          className="tradingview-widget-container"
          style={{ height: '100%', width: '100%', borderRadius: '0.75rem', overflow: 'hidden' }}
        />
      </div>
    </div>
  );
};

export default HomePage;
