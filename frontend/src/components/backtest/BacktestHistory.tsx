import type React from 'react';
import { useEffect, useState, useCallback } from 'react';
import { RiDeleteBin6Line, RiRefreshLine } from '@remixicon/react';
import { cn } from '../../utils/cn';
import { Badge } from '../common';
import { backtestEngineApi, type TaskListItem } from '../../api/backtestEngine';
import type { BacktestTask } from './BacktestAnalysis';
import { mapPayloadToResultData } from '../../utils/backtestPayload';

interface Props {
  // 点击行加载详情后回调,父级用 BacktestTask 切换到 BacktestResult 视图
  onSelect?: (task: BacktestTask) => void;
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// 解析 pipeline_info(扁平 / 旧嵌套两种结构皆兼容)
function extractStrategyName(item: TaskListItem): string {
  const pi = item.pipeline_info;
  if (!pi) return '旧版任务';
  if (pi.strategy_class) return pi.strategy_class;
  if (pi.strategies && pi.strategies.length > 0) {
    const first = pi.strategies[0];
    return (first.name as string) || (first.class_name as string) || '未知策略';
  }
  return '旧版任务';
}

const BacktestHistory: React.FC<Props> = ({ onSelect }) => {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [showDeleted, setShowDeleted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await backtestEngineApi.listTasks(showDeleted);
      setTasks(list);
    } catch {
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, [showDeleted]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  const handleOpen = async (item: TaskListItem) => {
    if (!onSelect || item.deleted) return;
    setOpeningId(item.task_id);
    try {
      const detail = await backtestEngineApi.getResult(item.task_id);
      const result = detail.result ? mapPayloadToResultData(detail.result) : null;
      // pipeline_info 兼容扁平 / 旧嵌套两种结构,提取 frequency 作 period 显示
      const pi = detail.pipeline_info as Record<string, unknown> | null | undefined;
      const params = (pi?.params as Record<string, unknown> | undefined) || {};
      const frequency =
        (params.frequency as string | undefined) ||
        (pi?.frequency_override as string | undefined) ||
        '--';
      const symbols = pi?.symbols as string[] | undefined;
      const market = (pi?.market as string | undefined) || 'A';
      const status: BacktestTask['status'] =
        item.status === 'success'
          ? 'completed'
          : item.status === 'failed'
            ? 'failed'
            : 'running';
      const task: BacktestTask = {
        taskId: item.task_id,
        status,
        mode: symbols && symbols.length === 1 ? 'single' : 'market',
        strategyName: extractStrategyName(item),
        symbol: symbols && symbols.length === 1 ? symbols[0] : undefined,
        market,
        period: frequency,
        startDate: detail.start_date || item.start_date || '',
        endDate: detail.end_date || item.end_date || '',
        capital: 0,
        commission: 0,
        result,
        error: detail.error,
        createdAt: detail.created_at || item.created_at,
        params,
      };
      onSelect(task);
    } catch (err) {
      console.error('加载回测详情失败', err);
    } finally {
      setOpeningId(null);
    }
  };

  const handleDelete = async (taskId: string) => {
    setDeletingId(taskId);
    try {
      await backtestEngineApi.deleteTask(taskId);
      await refresh();
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-border/30 px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-foreground">回测历史</span>
          <span className="text-xs text-muted-text">共 {tasks.length} 条</span>
        </div>
        <div className="flex items-center gap-3">
          <label className="inline-flex items-center gap-1.5 text-xs text-secondary-text">
            <input
              type="checkbox"
              checked={showDeleted}
              onChange={(e) => setShowDeleted(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-border accent-cyan"
            />
            显示已删除
          </label>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="inline-flex items-center gap-1 text-xs text-secondary-text hover:text-foreground disabled:opacity-50"
            title="刷新"
          >
            <RiRefreshLine className={cn('h-4 w-4', loading && 'animate-spin')} />
            刷新
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tasks.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-secondary-text">
                {loading ? '加载中...' : '暂无回测记录'}
              </p>
              {!loading && (
                <p className="mt-1 text-xs text-muted-text">运行回测后，结果会自动保存在这里</p>
              )}
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">任务 ID</th>
                  <th className="px-3 py-2">策略</th>
                  <th className="px-3 py-2">日期范围</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">创建时间</th>
                  <th className="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => {
                  const isDeleted = task.deleted;
                  return (
                    <tr
                      key={task.task_id}
                      onClick={() => !isDeleted && handleOpen(task)}
                      className={cn(
                        'border-b border-border/20',
                        isDeleted
                          ? 'bg-muted/20 text-muted-text'
                          : 'cursor-pointer hover:bg-hover/30',
                        openingId === task.task_id && 'opacity-60',
                      )}
                      title={!isDeleted ? '点击查看详情' : undefined}
                    >
                      <td className="px-3 py-2 font-mono text-xs">{task.task_id}</td>
                      <td className="px-3 py-2">
                        {extractStrategyName(task)}
                        {isDeleted && (
                          <Badge variant="default" className="ml-2">
                            已删除
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs tabular-nums">
                        {task.start_date && task.end_date
                          ? `${task.start_date} ~ ${task.end_date}`
                          : '--'}
                      </td>
                      <td className="px-3 py-2">
                        <Badge
                          variant={
                            task.status === 'success'
                              ? 'success'
                              : task.status === 'failed'
                                ? 'danger'
                                : 'default'
                          }
                        >
                          {task.status === 'success'
                            ? '完成'
                            : task.status === 'failed'
                              ? '失败'
                              : '运行中'}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-xs tabular-nums">
                        {formatDateTime(task.created_at)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {!isDeleted && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(task.task_id);
                            }}
                            disabled={deletingId === task.task_id}
                            className="inline-flex items-center gap-1 text-xs text-danger hover:text-danger/80 disabled:opacity-50"
                            title="软删除"
                          >
                            <RiDeleteBin6Line className="h-3.5 w-3.5" />
                            删除
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default BacktestHistory;
