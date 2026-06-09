import type React from 'react';
import { RiArrowLeftLine } from '@remixicon/react';
import { Badge } from '../common';
import BacktestResult from './BacktestResult';
import RadarResultView from './RadarResultView';
import type { BacktestTask } from './BacktestAnalysis';
import { marketLabel } from '../../utils/marketLabel';

interface Props {
  task: BacktestTask;
  onBack: () => void;
}

// 参数 key → 中文标签(没匹配的保持原 key)
// 与 strategies/examples/*.py 中各 Strategy.params 的 label 对齐,
// 用于历史详情(无 strategyInfo 时)显示
const PARAM_LABELS: Record<string, string> = {
  min_dividend_years: '最低分红年限',
  pe_min: 'PE最小值',
  pe_max: 'PE最大值',
  pe_pb_min: 'PE×PB 下限',
  pe_pb_max: 'PE×PB 上限',
  min_roe: '最低 ROE (%)',
  ma_fast: '快线周期',
  ma_mid: '中线周期',
  ma_slow: '慢线周期',
  ma_window: '突破 MA 窗口(0=关闭择时)',
  tangle_threshold: '缠绕阈值',
  tangle_months: '缠绕月数',
  spread_months: '发散月数',
  spread_threshold: '发散阈值',
  vol_red_bars: '连阳根数',
  buy_weeks: '分批买入周数',
  max_holdings: '最大持股只数',
  max_per_stock_pct: '单股仓位绝对上限',
  threshold: '差值阈值',
  pe_sell_enabled: '启用 PE 多轮分批卖出',
  pe_sell_threshold: 'PE 触发阈值',
  pe_sell_chain_threshold: '链式模式 PE 阈值',
  pe_sell_pct1: '第 1 轮卖出比例',
  pe_sell_pct_n: '第 2 轮起卖出比例',
  pe_sell_breakout_pct: '新轮触发突破阈值',
  pe_sell_batches: '每轮分批数',
  sell_pe_pb_max: 'PE*PB 退出阈值(0=关)',
  sell_below_ma: '月线 MA 退出',
  use_trap_rating_soft: 'L2.5 软评分模式',
  frequency: '执行频率',
};

function formatParamValue(v: unknown): string {
  if (v == null) return '--';
  if (typeof v === 'boolean') return v ? '是' : '否';
  if (typeof v === 'number') return String(v);
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

const BacktestDetail: React.FC<Props> = ({ task, onBack }) => {
  const params = task.params || {};
  const paramEntries = Object.entries(params);

  return (
    <div className="flex h-full w-full min-h-0 overflow-hidden">
      {/* Left: read-only config + task ID */}
      <aside className="flex w-80 flex-shrink-0 flex-col overflow-hidden border-r border-border/30 bg-card/20">
        <div className="flex-shrink-0 border-b border-border/30 px-4 py-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1 text-xs text-secondary-text hover:text-foreground"
          >
            <RiArrowLeftLine className="h-3.5 w-3.5" />
            返回历史
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {/* Task meta */}
          <div className="mb-4">
            <h3 className="text-sm font-semibold text-foreground">{task.strategyName}</h3>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  task.status === 'completed'
                    ? 'success'
                    : task.status === 'failed'
                      ? 'danger'
                      : 'default'
                }
              >
                {task.status === 'completed' ? '完成' : task.status === 'failed' ? '失败' : '运行中'}
              </Badge>
              {task.period && task.period !== '--' && (
                <span className="text-xs text-muted-text">{task.period}</span>
              )}
            </div>
          </div>

          {/* Task ID */}
          <DetailRow label="任务 ID">
            <span className="font-mono text-xs">{task.taskId}</span>
          </DetailRow>

          {/* Date range */}
          {(task.startDate || task.endDate) && (
            <DetailRow label="日期范围">
              <span className="tabular-nums">
                {task.startDate || '--'} ~ {task.endDate || '--'}
              </span>
            </DetailRow>
          )}

          {/* Symbol(s) */}
          {task.symbol && (
            <DetailRow label="标的">
              <span className="font-mono">{task.symbol}</span>
            </DetailRow>
          )}

          {task.market && !task.symbol && (
            <DetailRow label="市场">{marketLabel(task.market)}</DetailRow>
          )}

          {/* Created time */}
          {task.createdAt && (
            <DetailRow label="创建时间">
              <span className="tabular-nums">{formatDateTime(task.createdAt)}</span>
            </DetailRow>
          )}

          {/* Strategy params */}
          {paramEntries.length > 0 && (
            <div className="mt-4 rounded-lg border border-border/40 bg-elevated/30 p-3">
              <h4 className="mb-2 text-xs font-medium text-secondary-text">策略参数</h4>
              <div className="space-y-1.5">
                {paramEntries.map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="text-muted-text" title={k}>
                      {PARAM_LABELS[k] || k}
                    </span>
                    <span className="font-mono tabular-nums text-foreground">{formatParamValue(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* Right: scan-radar 任务展示 hits 表,其余复用 BacktestResult */}
      <main className="min-h-0 flex-1 overflow-y-auto">
        {task.taskType === 'scan-radar' ? (
          <RadarResultView
            payload={task.radarPayload}
            strategyName={task.strategyName}
            market={task.market}
          />
        ) : (
          <BacktestResult task={task} />
        )}
      </main>
    </div>
  );
};

const DetailRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="mb-2 flex items-baseline justify-between gap-2 text-xs">
    <span className="text-muted-text">{label}</span>
    <span className="text-foreground">{children}</span>
  </div>
);

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default BacktestDetail;
