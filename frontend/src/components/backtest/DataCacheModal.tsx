import type React from 'react';
import { useState } from 'react';
import { createPortal } from 'react-dom';
import { backtestCacheApi, type CacheMarket, type CacheStatusMap } from '../../api/backtestCache';

interface Props {
  isOpen: boolean;
  status: CacheStatusMap | null;
  onClose: () => void;
  onRefresh: () => void;
}

const MARKET_LABELS: Record<CacheMarket, string> = {
  A: 'A 股',
  HK: '港股',
  US: '美股',
};

const DataCacheModal: React.FC<Props> = ({ isOpen, status, onClose, onRefresh }) => {
  const [selected, setSelected] = useState<CacheMarket>('A');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!isOpen) return null;

  const cur = status?.[selected];
  const isLoading = cur?.status === 'loading';

  const handleLoad = async () => {
    setBusy(true);
    setErr(null);
    try {
      await backtestCacheApi.load(selected);
      onRefresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleInvalidate = async () => {
    setBusy(true);
    setErr(null);
    try {
      await backtestCacheApi.invalidate(selected);
      onRefresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const dialog = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-4 w-full max-w-md rounded-xl border border-border/70 bg-elevated p-6 shadow-2xl animate-in fade-in zoom-in duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-1 text-lg font-medium text-foreground">加载市场数据</h3>
        <p className="mb-4 text-xs text-secondary-text">
          选择市场,加载完成后该市场的回测会直接使用内存数据(零 IO)。
        </p>

        <div className="mb-4 flex gap-2">
          {(['A', 'HK', 'US'] as CacheMarket[]).map((m) => {
            const s = status?.[m];
            const loaded = s?.loaded;
            return (
              <button
                key={m}
                type="button"
                onClick={() => setSelected(m)}
                className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-all ${
                  selected === m
                    ? 'border-cyan bg-cyan/10 text-foreground'
                    : 'border-border/50 text-secondary-text hover:text-foreground'
                }`}
              >
                <div className="font-medium">{MARKET_LABELS[m]}</div>
                <div className="mt-0.5 text-[10px] text-muted-text">
                  {loaded ? `已加载 ${s?.symbols}` : s?.status === 'loading' ? '加载中...' : '未加载'}
                </div>
              </button>
            );
          })}
        </div>

        {cur && (
          <div className="mb-4 rounded-lg border border-border/40 bg-card/30 p-3 text-xs">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-secondary-text">{MARKET_LABELS[selected]} 状态</span>
              <span
                className={
                  cur.status === 'loaded'
                    ? 'text-emerald-400'
                    : cur.status === 'loading'
                      ? 'text-amber-400'
                      : cur.status === 'failed'
                        ? 'text-rose-400'
                        : 'text-muted-text'
                }
              >
                {cur.status === 'loaded' ? '已加载' : cur.status === 'loading' ? '加载中' : cur.status === 'failed' ? '失败' : '未加载'}
              </span>
            </div>
            {cur.loaded && (
              <div className="text-muted-text">
                K 线 {cur.symbols} 只 · 估值 {cur.valuation_count} · 分红 {cur.dividend_count} · 财务{' '}
                {cur.financial_count}
              </div>
            )}
            {cur.status === 'loading' && (
              <div className="mt-1 text-muted-text">{cur.progress.phase}</div>
            )}
            {cur.error && <div className="mt-1 text-rose-400">{cur.error}</div>}
          </div>
        )}

        {err && (
          <div className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </div>
        )}

        <div className="flex justify-end gap-2">
          {cur?.loaded && (
            <button
              type="button"
              onClick={handleInvalidate}
              disabled={busy}
              className="rounded-lg border border-border/50 px-3 py-1.5 text-xs text-secondary-text transition-colors hover:text-foreground disabled:opacity-50"
            >
              清除缓存
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border/50 px-3 py-1.5 text-xs text-secondary-text transition-colors hover:text-foreground"
          >
            关闭
          </button>
          <button
            type="button"
            onClick={handleLoad}
            disabled={busy || isLoading}
            className="btn-primary rounded-lg px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? '加载中...' : cur?.loaded ? '重新加载' : '加载'}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
};

export default DataCacheModal;
