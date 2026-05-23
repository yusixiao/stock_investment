import type React from 'react';
import { useState } from 'react';
import BacktestHistory from './BacktestHistory';
import BacktestDetail from './BacktestDetail';
import type { BacktestTask } from './BacktestAnalysis';

const BacktestHistoryView: React.FC = () => {
  const [detailTask, setDetailTask] = useState<BacktestTask | null>(null);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {detailTask ? (
          <BacktestDetail task={detailTask} onBack={() => setDetailTask(null)} />
        ) : (
          <BacktestHistory onSelect={setDetailTask} />
        )}
      </div>
    </div>
  );
};

export default BacktestHistoryView;
