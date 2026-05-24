import React from 'react';
import { cn } from '../utils/cn';
import type { ProgressStep } from '../stores/agentChatStore';

// CPA 三阶段:工具名 → 阶段标签
const PHASE_DEFS: Array<{ tool: string; label: string; desc: string }> = [
  { tool: 'phase1_data_pack', label: 'Phase 1', desc: '数据包构建' },
  { tool: 'phase3_quant', label: 'Phase 3.1', desc: '量化分析' },
  { tool: 'phase3_valuation', label: 'Phase 3.2', desc: '估值与报告' },
];

type PhaseStatus = 'pending' | 'running' | 'success' | 'failed';

interface PhaseState {
  tool: string;
  label: string;
  desc: string;
  status: PhaseStatus;
  duration?: number;
}

// 把扁平 ProgressStep[] 聚合成三阶段状态
function aggregatePhases(steps: ProgressStep[]): PhaseState[] {
  return PHASE_DEFS.map((def) => {
    const start = steps.find((s) => s.type === 'tool_start' && s.tool === def.tool);
    const done = steps.find((s) => s.type === 'tool_done' && s.tool === def.tool);

    let status: PhaseStatus = 'pending';
    if (done) {
      status = done.success === false ? 'failed' : 'success';
    } else if (start) {
      status = 'running';
    }

    return {
      tool: def.tool,
      label: def.label,
      desc: def.desc,
      status,
      duration: done?.duration,
    };
  });
}

const STATUS_DOT: Record<PhaseStatus, string> = {
  pending: 'bg-muted-text/30',
  running: 'bg-cyan animate-pulse',
  success: 'bg-emerald-500',
  failed: 'bg-rose-500',
};

const STATUS_TEXT: Record<PhaseStatus, string> = {
  pending: 'text-muted-text/60',
  running: 'text-cyan',
  success: 'text-emerald-400',
  failed: 'text-rose-400',
};

const STATUS_LABEL: Record<PhaseStatus, string> = {
  pending: '等待',
  running: '进行中',
  success: '完成',
  failed: '失败',
};

interface PhaseProgressCardProps {
  steps: ProgressStep[];
  compact?: boolean;
  className?: string;
}

const PhaseProgressCard: React.FC<PhaseProgressCardProps> = ({
  steps,
  compact = false,
  className,
}) => {
  const phases = aggregatePhases(steps);
  // 全部 pending 时不渲染(避免空白卡片)
  if (phases.every((p) => p.status === 'pending')) return null;

  return (
    <div
      className={cn(
        'rounded-xl border border-border/40 bg-surface/40 p-3 space-y-2',
        compact && 'p-2 space-y-1.5',
        className,
      )}
      role="status"
      aria-label="分析进度"
    >
      {phases.map((p, idx) => {
        const isLast = idx === phases.length - 1;
        return (
          <div key={p.tool} className="flex items-center gap-3 text-xs">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  'w-2 h-2 rounded-full flex-shrink-0',
                  STATUS_DOT[p.status],
                )}
              />
              {!isLast && (
                <span className="w-px h-3 bg-border/40 mt-0.5" />
              )}
            </div>
            <div className="flex items-baseline gap-2 flex-1 min-w-0">
              <span className="font-medium text-secondary-text">{p.label}</span>
              <span className="text-muted-text truncate">{p.desc}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className={cn('text-[11px]', STATUS_TEXT[p.status])}>
                {STATUS_LABEL[p.status]}
              </span>
              {p.duration !== undefined && (
                <span className="text-[11px] text-muted-text/70 tabular-nums">
                  {p.duration.toFixed(1)}s
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default PhaseProgressCard;
