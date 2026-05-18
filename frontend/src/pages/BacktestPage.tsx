import type React from 'react';
import { useState, useEffect } from 'react';
import { RiLineChartLine, RiRadarLine, RiPulseLine } from '@remixicon/react';
import { cn } from '../utils/cn';
import BacktestAnalysis from '../components/backtest/BacktestAnalysis';
import StrategyRadar from '../components/backtest/StrategyRadar';
import MarketMonitor from '../components/backtest/MarketMonitor';

type TabKey = 'backtest' | 'radar' | 'monitor';

interface TabDef {
  key: TabKey;
  label: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  { key: 'backtest', label: '策略回测', icon: <RiLineChartLine className="h-4 w-4" /> },
  { key: 'radar', label: '策略雷达', icon: <RiRadarLine className="h-4 w-4" /> },
  { key: 'monitor', label: '盘面监控', icon: <RiPulseLine className="h-4 w-4" /> },
];

const BacktestPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('backtest');

  useEffect(() => {
    document.title = '策略回测 - DSA';
  }, []);

  return (
    <div className="flex h-full flex-col">
      <nav className="flex-shrink-0 border-b border-border/40 px-4">
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'inline-flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
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

      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'backtest' && <BacktestAnalysis />}
        {activeTab === 'radar' && <StrategyRadar />}
        {activeTab === 'monitor' && <MarketMonitor />}
      </div>
    </div>
  );
};

export default BacktestPage;
