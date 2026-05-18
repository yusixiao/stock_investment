import type React from 'react';
import { useState } from 'react';
import { cn } from '../../utils/cn';
import { Badge } from '../common';
import type { BacktestTask } from './BacktestAnalysis';

interface Props {
  onSelect: (task: BacktestTask) => void;
}

type HistoryTab = 'stock' | 'market';

const MOCK_HISTORY: BacktestTask[] = [];

const BacktestHistory: React.FC<Props> = ({ onSelect }) => {
  const [tab, setTab] = useState<HistoryTab>('stock');
  const tasks = MOCK_HISTORY.filter(t =>
    tab === 'stock' ? t.mode === 'single' : t.mode === 'market'
  );

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex-shrink-0 border-b border-border/30 px-4 py-2">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => setTab('stock')}
            className={cn(
              'text-sm font-medium transition-colors',
              tab === 'stock' ? 'text-foreground' : 'text-secondary-text hover:text-foreground',
            )}
          >
            个股回测记录
          </button>
          <button
            type="button"
            onClick={() => setTab('market')}
            className={cn(
              'text-sm font-medium transition-colors',
              tab === 'market' ? 'text-foreground' : 'text-secondary-text hover:text-foreground',
            )}
          >
            全市场回测记录
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tasks.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-secondary-text">暂无回测记录</p>
              <p className="mt-1 text-xs text-muted-text">运行回测后，结果会自动保存在这里</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">策略</th>
                  {tab === 'stock' && <th className="px-3 py-2">股票</th>}
                  <th className="px-3 py-2">市场</th>
                  <th className="px-3 py-2">周期</th>
                  <th className="px-3 py-2 text-right">收益率</th>
                  <th className="px-3 py-2 text-right">最大回撤</th>
                  <th className="px-3 py-2 text-right">夏普比</th>
                  <th className="px-3 py-2 text-right">胜率</th>
                  <th className="px-3 py-2 text-right">交易次数</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">时间</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr
                    key={task.taskId}
                    onClick={() => onSelect(task)}
                    className="cursor-pointer border-b border-border/20 hover:bg-hover/30"
                  >
                    <td className="px-3 py-2 font-medium">{task.strategyName}</td>
                    {tab === 'stock' && <td className="px-3 py-2 font-mono">{task.symbol}</td>}
                    <td className="px-3 py-2">{task.market}</td>
                    <td className="px-3 py-2">{task.period === 'daily' ? '日线' : task.period === 'weekly' ? '周线' : '月线'}</td>
                    <td className={cn('px-3 py-2 text-right tabular-nums', task.result?.totalReturn != null && task.result.totalReturn >= 0 ? 'text-success' : 'text-danger')}>
                      {task.result?.totalReturn != null ? `${(task.result.totalReturn * 100).toFixed(2)}%` : '--'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-danger">
                      {task.result?.maxDrawdown != null ? `${(task.result.maxDrawdown * 100).toFixed(2)}%` : '--'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {task.result?.sharpeRatio?.toFixed(2) ?? '--'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {task.result?.winRate != null ? `${(task.result.winRate * 100).toFixed(1)}%` : '--'}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {task.result?.totalTrades ?? '--'}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={task.status === 'completed' ? 'success' : task.status === 'failed' ? 'danger' : 'default'}>
                        {task.status === 'completed' ? '完成' : task.status === 'failed' ? '失败' : '运行中'}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-text tabular-nums">
                      {new Date(task.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
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

export default BacktestHistory;
