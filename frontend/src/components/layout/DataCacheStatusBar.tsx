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

  const renderPill = (m: CacheMarket) => {
    const s = status?.[m];
    let text: string;
    let color: string;
    if (s?.status === 'loaded') {
      text = `已加载 ${s.symbols} 只 · ${s.last_date ?? '-'}`;
      color = 'text-emerald-400';
    } else if (s?.status === 'loading') {
      text = '加载中…';
      color = 'text-amber-400';
    } else if (s?.status === 'failed') {
      text = '失败';
      color = 'text-rose-400';
    } else {
      text = '未加载';
      color = 'text-muted-text';
    }
    return (
      <span key={m} className="whitespace-nowrap tabular-nums">
        <span className="text-secondary-text">{MARKET_LABELS[m]}</span>
        <span className={`ml-1 ${color}`}>{text}</span>
      </span>
    );
  };

  return (
    <>
      <div
        className="pointer-events-auto fixed bottom-3 left-3 z-30 hidden items-center gap-2 rounded-xl border border-border/60 bg-card/85 px-2.5 py-1.5 text-[11px] shadow-soft-card backdrop-blur-md lg:flex"
        aria-label="数据缓存状态"
      >
        <button
          type="button"
          onClick={() => {
            refresh();
            setModalOpen(true);
          }}
          className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-elevated/60 px-2 py-1 text-xs font-medium text-secondary-text transition-colors hover:text-foreground"
          aria-label="打开数据缓存加载弹窗"
        >
          <Database className="h-3.5 w-3.5" />
          <span>数据</span>
        </button>
        <div className="flex items-center gap-3 pr-1">
          {(['A', 'HK', 'US'] as CacheMarket[]).map(renderPill)}
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
