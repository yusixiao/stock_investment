import type React from 'react';
import { useState } from 'react';
import { RiAddLine, RiDeleteBinLine } from '@remixicon/react';
import { Badge } from '../common';

interface MonitorItem {
  id: string;
  symbol: string;
  name: string;
  strategy: string;
  lastSignal?: {
    type: 'buy' | 'sell';
    date: string;
    price: number;
  };
  status: 'active' | 'paused';
}

const MarketMonitor: React.FC = () => {
  const [monitors, setMonitors] = useState<MonitorItem[]>([]);
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-border/30 bg-card/20 px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-foreground">盘面监控</h3>
            <p className="text-xs text-muted-text">实时监控策略信号，及时发现买卖机会</p>
          </div>
          <button
            type="button"
            onClick={() => setShowAdd(!showAdd)}
            className="btn-secondary flex items-center gap-1.5 text-xs"
          >
            <RiAddLine className="h-3.5 w-3.5" />
            添加监控
          </button>
        </div>
      </div>

      {/* Add Monitor Form */}
      {showAdd && (
        <div className="flex-shrink-0 border-b border-border/30 bg-card/40 px-4 py-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-secondary-text">股票代码</label>
              <input
                type="text"
                placeholder="输入股票代码"
                className="input-surface input-focus-glow h-9 w-36 rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-secondary-text">策略</label>
              <select className="input-surface input-focus-glow h-9 w-40 appearance-none rounded-lg border bg-transparent px-3 text-sm transition-all focus:outline-none">
                <option value="">请选择策略</option>
                <option value="ma_cross">均线交叉</option>
                <option value="macd_divergence">MACD背离</option>
                <option value="rsi_oversold">RSI超卖反弹</option>
              </select>
            </div>
            <button type="button" className="btn-primary h-9 text-xs">
              确认添加
            </button>
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="h-9 px-3 text-xs text-secondary-text hover:text-foreground"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Monitor List */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {monitors.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border border-dashed border-border/60 bg-card/30">
                <svg className="h-7 w-7 text-secondary-text" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
              </div>
              <p className="text-sm text-secondary-text">暂无监控项</p>
              <p className="mt-1 text-xs text-muted-text">添加股票和策略组合，系统将自动监控信号触发</p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {monitors.map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between rounded-xl border border-border/40 bg-card/50 p-4"
              >
                <div className="flex items-center gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">{item.symbol}</span>
                      <span className="text-sm text-secondary-text">{item.name}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-text">{item.strategy}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {item.lastSignal ? (
                    <Badge variant={item.lastSignal.type === 'buy' ? 'success' : 'danger'}>
                      {item.lastSignal.type === 'buy' ? '买入信号' : '卖出信号'} · {item.lastSignal.date}
                    </Badge>
                  ) : (
                    <span className="text-xs text-muted-text">暂无信号</span>
                  )}
                  <button
                    type="button"
                    className="text-muted-text hover:text-danger transition-colors"
                    onClick={() => setMonitors(monitors.filter(m => m.id !== item.id))}
                  >
                    <RiDeleteBinLine className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MarketMonitor;
