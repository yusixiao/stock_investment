import type React from 'react';
import { useState, useEffect } from 'react';
import { RiLineChartLine, RiRadarLine, RiPulseLine, RiHistoryLine } from '@remixicon/react';
import { cn } from '../utils/cn';
import BacktestAnalysis from '../components/backtest/BacktestAnalysis';
import StrategyRadar from '../components/backtest/StrategyRadar';
import MarketMonitor from '../components/backtest/MarketMonitor';
import BacktestHistoryView from '../components/backtest/BacktestHistoryView';

type TabKey = 'backtest' | 'radar' | 'monitor' | 'history';

interface TabDef {
  key: TabKey;
  label: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  { key: 'backtest', label: '策略回测', icon: <RiLineChartLine className="h-4 w-4" /> },
  { key: 'radar', label: '策略雷达', icon: <RiRadarLine className="h-4 w-4" /> },
  { key: 'monitor', label: '盘面监控', icon: <RiPulseLine className="h-4 w-4" /> },
  { key: 'history', label: '历史记录', icon: <RiHistoryLine className="h-4 w-4" /> },
];

const BacktestPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('backtest');

  useEffect(() => {
    document.title = '策略回测 - DSA';
  }, []);

  return (
    <div className="flex h-full flex-col">
      <nav className="page-tabs flex-shrink-0 border-b border-border/40 px-4" aria-label="回测工作区">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="回测工作区标签">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              id={`tab-${tab.key}`}
              role="tab"
              aria-selected={activeTab === tab.key}
              aria-controls={activeTab === tab.key ? `panel-${tab.key}` : undefined}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'inline-flex min-h-11 items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-[border-color,color,background-color] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15',
                activeTab === tab.key
                  ? 'border-cyan text-cyan'
                  : 'border-transparent text-secondary-text hover:text-foreground',
              )}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      <div
        id={`panel-${activeTab}`}
        role="tabpanel"
        aria-labelledby={`tab-${activeTab}`}
        className="min-h-0 flex-1 overflow-hidden"
      >
        {activeTab === 'backtest' && <BacktestAnalysis />}
        {activeTab === 'radar' && <StrategyRadar />}
        {activeTab === 'monitor' && <MarketMonitor />}
        {activeTab === 'history' && <BacktestHistoryView />}
      </div>
    </div>
  );
};

export default BacktestPage;
