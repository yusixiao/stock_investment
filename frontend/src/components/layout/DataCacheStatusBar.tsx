/**
 * 数据缓存状态浮动条(页面左下角全局可见)。
 *
 * 显示:[数据] 按钮 + A/H/US 三市场加载状态(已加载只数 + 数据截止日)。
 * 点击按钮(或任一市场 pill)→ 打开 DataCacheModal 加载/失效缓存。
 *
 * 全局轮询:任一市场 loading 时每 2s 刷新,否则 60s 一次保持时效。
 */
import type React from 'react';
import { useState, useEffect, useCallback } from 'react';
import { Database } from 'lucide-react';
import DataCacheModal from '../backtest/DataCacheModal';
import { backtestCacheApi, type CacheMarket, type CacheStatusMap } from '../../api/backtestCache';

const MARKET_LABELS: Record<CacheMarket, string> = {
  A: 'A 股',
  HK: '港股',
  US: '美股',
};

const DataCacheStatusBar: React.FC = () => {
  const [status, setStatus] = useState<CacheStatusMap | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(() => {
    backtestCacheApi
      .status()
      .then(setStatus)
      .catch(() => {
        // 后端未启动时静默忽略
      });
  }, []);

  useEffect(() => {
    refresh();
    const idle = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(idle);
  }, [refresh]);

  // 任一市场 loading 时,提速到 2s 轮询
  useEffect(() => {
    if (!status) return;
    const anyLoading = Object.values(status).some((s) => s.status === 'loading');
    if (!anyLoading) return;
    const t = window.setInterval(refresh, 2_000);
    return () => window.clearInterval(t);
  }, [status, refresh]);

  const renderBlock = (m: CacheMarket) => {
    const s = status?.[m];
    let statusText: string;
    let dateText: string;
    let color: string;
    if (s?.status === 'loaded') {
      statusText = `已加载 ${s.symbols} 只`;
      dateText = s.last_date ?? '-';
      color = 'text-emerald-400';
    } else if (s?.status === 'loading') {
      statusText = '加载中…';
      dateText = '-';
      color = 'text-amber-400';
    } else if (s?.status === 'failed') {
      statusText = '失败';
      dateText = '-';
      color = 'text-rose-400';
    } else {
      statusText = '未加载';
      dateText = '-';
      color = 'text-muted-text';
    }
    return (
      <div
        key={m}
        className="flex flex-col items-center gap-0.5 py-1 text-center leading-tight tabular-nums"
      >
        <span className="whitespace-nowrap text-sm font-medium text-secondary-text">{MARKET_LABELS[m]}</span>
        <span className={`whitespace-nowrap text-sm ${color}`}>{statusText}</span>
        <span className={`whitespace-nowrap text-sm ${color}`}>{dateText}</span>
      </div>
    );
  };

  return (
    <>
      <div
        className="pointer-events-auto fixed bottom-3 left-3 z-30 hidden w-[132px] flex-col items-stretch gap-1.5 rounded-2xl border border-border/60 bg-card/85 px-2 py-2 text-sm shadow-soft-card backdrop-blur-md lg:flex"
        aria-label="数据缓存状态"
      >
        <button
          type="button"
          onClick={() => {
            refresh();
            setModalOpen(true);
          }}
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-border/60 bg-elevated/60 px-3 text-sm font-medium text-secondary-text transition-all hover:border-border hover:bg-hover hover:text-foreground"
          aria-label="打开数据缓存加载弹窗"
        >
          <Database className="h-5 w-5" />
          <span>加载</span>
        </button>
        <div className="flex flex-col">
          {(['A', 'HK', 'US'] as CacheMarket[]).map(renderBlock)}
        </div>
      </div>

      <DataCacheModal
        isOpen={modalOpen}
        status={status}
        onClose={() => setModalOpen(false)}
        onRefresh={refresh}
      />
    </>
  );
};

export default DataCacheStatusBar;
