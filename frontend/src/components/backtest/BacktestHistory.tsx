import type React from 'react';
import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  RiArrowDownSLine,
  RiArrowUpSLine,
  RiExpandUpDownLine,
  RiRefreshLine,
} from '@remixicon/react';
import { cn } from '../../utils/cn';
import { Badge, Button, ConfirmDialog, Tooltip } from '../common';
import { backtestEngineApi, type TaskListItem } from '../../api/backtestEngine';
import type { BacktestTask } from './BacktestAnalysis';
import {
  buildBacktestTask,
  extractMarketLabel,
  extractParams,
  extractStrategyName,
  isMonitorTask,
} from './historyTaskAdapter';

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

// 参数 tooltip 内容:多行 key: value
const ParamsTooltip: React.FC<{ params: Record<string, unknown> | null }> = ({ params }) => {
  if (!params || Object.keys(params).length === 0) {
    return <span className="text-muted-text">无参数</span>;
  }
  return (
    <div className="flex flex-col gap-0.5 font-mono text-[11px] leading-5">
      {Object.entries(params).map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-secondary-text">{k}:</span>
          <span className="text-foreground">
            {Array.isArray(v) ? `[${v.join(', ')}]` : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
};

const BacktestHistory: React.FC<Props> = ({ onSelect }) => {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [showDeleted, setShowDeleted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  // 排序:null = 默认(按 created_at 后端原序);'asc' / 'desc' = 按总收益率
  const [returnSort, setReturnSort] = useState<'asc' | 'desc' | null>(null);
  const sortedTasks = useMemo(() => {
    const arr = [...tasks];
    arr.sort((a, b) => {
      const executionOrder = Number(b.execution_status === 'active') - Number(a.execution_status === 'active');
      if (executionOrder !== 0) return executionOrder;
      if (!returnSort) return 0;
      // 三态:有效数 → 排序;非数 / null → 沉到末尾(无论升降)
      const ra = a.summary?.total_return as number | null | undefined;
      const rb = b.summary?.total_return as number | null | undefined;
      const va = typeof ra === 'number' && Number.isFinite(ra) ? ra : null;
      const vb = typeof rb === 'number' && Number.isFinite(rb) ? rb : null;
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      return returnSort === 'asc' ? va - vb : vb - va;
    });
    return arr;
  }, [tasks, returnSort]);

  const cycleReturnSort = useCallback(() => {
    // 三态循环:null → desc → asc → null
    setReturnSort((prev) => (prev === null ? 'desc' : prev === 'desc' ? 'asc' : null));
  }, []);

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
      const task = buildBacktestTask(item, detail);
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
      setDeleteConfirmId(null);
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
          <label className="inline-flex items-center gap-1.5 text-sm font-medium leading-5 text-secondary-text">
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
            className="inline-flex items-center gap-1 text-sm font-medium leading-5 text-secondary-text hover:text-foreground disabled:opacity-50"
            title="刷新"
          >
            <RiRefreshLine className={cn('h-4 w-4', loading && 'animate-spin')} />
            刷新
          </button>
        </div>
      </div>
      <ConfirmDialog
        isOpen={deleteConfirmId !== null}
        title="删除回测记录"
        message="确认删除这条回测记录吗？删除后默认列表中将不再显示。"
        confirmText="确认删除"
        cancelText="取消"
        isDanger
        onConfirm={() => {
          if (deleteConfirmId) void handleDelete(deleteConfirmId);
        }}
        onCancel={() => setDeleteConfirmId(null)}
      />

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
                  <th className="px-3 py-2">市场</th>
                  <th className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={cycleReturnSort}
                      className="inline-flex items-center gap-0.5 text-xs text-secondary-text hover:text-foreground"
                      title="点击切换排序:降序 → 升序 → 默认"
                    >
                      总收益率
                      {returnSort === 'desc' ? (
                        <RiArrowDownSLine className="h-3.5 w-3.5 text-foreground" />
                      ) : returnSort === 'asc' ? (
                        <RiArrowUpSLine className="h-3.5 w-3.5 text-foreground" />
                      ) : (
                        <RiExpandUpDownLine className="h-3.5 w-3.5 opacity-50" />
                      )}
                    </button>
                  </th>
                  <th className="px-3 py-2">日期范围</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">创建时间</th>
                  <th className="px-3 py-2 text-center">操作</th>
                </tr>
              </thead>
              <tbody>
                {sortedTasks.map((task) => {
                  const isDeleted = task.deleted;
                  const totalReturn = task.summary?.total_return as number | null | undefined;
                  const hasReturn = typeof totalReturn === 'number' && Number.isFinite(totalReturn);
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
                        <Tooltip content={<ParamsTooltip params={extractParams(task)} />}>
                          <span className="cursor-help underline decoration-dotted decoration-border underline-offset-4">
                            {extractStrategyName(task)}
                          </span>
                        </Tooltip>
                        {isDeleted && (
                          <Badge variant="default" className="ml-2">
                            已删除
                          </Badge>
                        )}
                        {task.execution_status === 'active' && (
                          <Badge variant="success" className="ml-2">
                            执行中
                          </Badge>
                        )}
                        {isMonitorTask(task) && (
                          <Badge variant="default" className="ml-2">
                            监控触发
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs text-secondary-text">
                        {extractMarketLabel(task)}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-2 text-right text-xs tabular-nums',
                          hasReturn
                            ? totalReturn! >= 0
                              ? 'text-success'
                              : 'text-danger'
                            : 'text-muted-text',
                        )}
                      >
                        {hasReturn
                          ? `${totalReturn! >= 0 ? '+' : ''}${(totalReturn! * 100).toFixed(2)}%`
                          : '--'}
                      </td>
                      <td className="px-3 py-2 text-xs tabular-nums">
                        {task.start_date && task.end_date
                          ? `${task.start_date} ~ ${task.end_date}`
                          : '--'}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            'text-xs font-medium',
                            task.status === 'success'
                              ? 'text-success'
                              : task.status === 'failed'
                                ? 'text-danger'
                                : 'text-muted-text',
                          )}
                        >
                          {task.status === 'success'
                            ? '完成'
                            : task.status === 'failed'
                              ? '失败'
                              : '运行中'}
                        </span>
                      </td>
                        <td className="px-3 py-2 text-xs tabular-nums">
                          {formatDateTime(task.created_at)}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <div className="flex flex-wrap items-center justify-end gap-2">
                            {!isDeleted && (
                              <Button
                                type="button"
                                variant="danger-subtle"
                                size="sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setDeleteConfirmId(task.task_id);
                                }}
                                disabled={deletingId === task.task_id}
                                title="软删除"
                              >
                                删除
                              </Button>
                            )}
                          </div>
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
