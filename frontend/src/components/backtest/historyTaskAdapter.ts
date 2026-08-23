import type {
  BacktestResultPayload,
  ScanRadarPayload,
  TaskListItem,
  TaskPipelineInfo,
  TaskResult,
} from '../../api/backtestEngine';
import type { BacktestTask } from './BacktestAnalysis';
import { mapPayloadToResultData } from '../../utils/backtestPayload';

type PipelineInfo = TaskPipelineInfo | null | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readPipelineString(pipelineInfo: PipelineInfo, key: string): string | undefined {
  if (!pipelineInfo) return undefined;
  const value: unknown = isRecord(pipelineInfo) ? pipelineInfo[key] : undefined;
  return typeof value === 'string' ? value : undefined;
}

function readPipelineSymbols(pipelineInfo: PipelineInfo): string[] | undefined {
  const symbols = pipelineInfo?.symbols;
  return Array.isArray(symbols) && symbols.every((symbol) => typeof symbol === 'string')
    ? symbols
    : undefined;
}

function readFirstStrategy(pipelineInfo: PipelineInfo): Record<string, unknown> | null {
  const first = pipelineInfo?.strategies?.[0];
  return isRecord(first) ? first : null;
}

function readPipelineParams(pipelineInfo: PipelineInfo): Record<string, unknown> | null {
  if (!pipelineInfo) return null;
  if (isRecord(pipelineInfo.params)) return pipelineInfo.params;
  const first = readFirstStrategy(pipelineInfo);
  return first && isRecord(first.params) ? first.params : null;
}

function strategyNameFromPipeline(pipelineInfo: PipelineInfo): string {
  if (!pipelineInfo) return '旧版任务';
  const strategyName = readPipelineString(pipelineInfo, 'strategy_name');
  if (strategyName) return strategyName;
  const monitorName = readPipelineString(pipelineInfo, 'monitor_name');
  if (monitorName) return monitorName;
  const strategyClass = readPipelineString(pipelineInfo, 'strategy_class');
  if (strategyClass) return strategyClass;
  const first = readFirstStrategy(pipelineInfo);
  const name = first?.name;
  if (typeof name === 'string' && name) return name;
  const className = first?.class_name;
  return typeof className === 'string' && className ? className : '旧版任务';
}

export function extractStrategyName(item: TaskListItem): string {
  return strategyNameFromPipeline(item.pipeline_info);
}

export function isMonitorTask(item: TaskListItem): boolean {
  return item.task_type === 'monitor' || item.pipeline_info?.trigger_source === 'monitor';
}

export function extractMarketLabel(item: TaskListItem): string {
  const pipelineInfo = item.pipeline_info;
  if (!pipelineInfo) return '--';
  const symbols = readPipelineSymbols(pipelineInfo);
  if (symbols && symbols.length === 1) return symbols[0];
  const market = readPipelineString(pipelineInfo, 'market') || 'A';
  switch (market.toUpperCase()) {
    case 'A': return 'A 股';
    case 'HK': return '港股';
    case 'HK_CONNECT': return '港股通';
    case 'US': return '美股';
    default: return market;
  }
}

export function extractParams(item: TaskListItem): Record<string, unknown> | null {
  const pipelineInfo = item.pipeline_info;
  if (!pipelineInfo) return null;
  return readPipelineParams(pipelineInfo);
}

function extractParamsFromPipeline(pipelineInfo: PipelineInfo): Record<string, unknown> {
  return readPipelineParams(pipelineInfo) || {};
}

function isRadarPayload(value: unknown): value is ScanRadarPayload {
  if (!isRecord(value) || !isRecord(value.date_range)) return false;
  return typeof value.date_range.start === 'string' && typeof value.date_range.end === 'string';
}

function isBacktestResultPayload(value: unknown): value is BacktestResultPayload {
  return isRecord(value) && isRecord(value.metrics);
}

export function buildBacktestTask(item: TaskListItem, detail: TaskResult): BacktestTask {
  const pipelineInfo = {
    ...(isRecord(item.pipeline_info) ? item.pipeline_info : {}),
    ...(isRecord(detail.pipeline_info) ? detail.pipeline_info : {}),
  };
  const params = extractParamsFromPipeline(pipelineInfo);
  const frequency = typeof params.frequency === 'string' ? params.frequency : undefined;
  const frequencyOverride = readPipelineString(pipelineInfo, 'frequency_override');
  const pipelineFrequency = readPipelineString(pipelineInfo, 'frequency');
  const symbols = readPipelineSymbols(pipelineInfo);
  const taskType = detail.task_type || item.task_type;
  const isRadar = ['scan-radar', 'monitor'].includes(taskType);
  const radarPayload = isRadar && isRadarPayload(detail.result) ? detail.result : null;
  const result = !isRadar && isBacktestResultPayload(detail.result)
    ? mapPayloadToResultData(detail.result)
    : null;

  return {
    taskId: item.task_id,
    status: item.status === 'success'
      ? 'completed'
      : item.status === 'failed'
        ? 'failed'
        : item.status === 'interrupted'
          ? 'interrupted'
          : 'running',
    executionStatus: item.execution_status,
    executionAccountId: item.execution_account_id,
    mode: symbols && symbols.length === 1 ? 'single' : 'market',
    strategyName: strategyNameFromPipeline(pipelineInfo),
    symbol: symbols && symbols.length === 1 ? symbols[0] : undefined,
    market: readPipelineString(pipelineInfo, 'market') || 'A',
    period: frequency || frequencyOverride || pipelineFrequency || '--',
    startDate: radarPayload?.date_range?.start || detail.start_date || item.start_date || '',
    endDate: radarPayload?.date_range?.end || detail.end_date || item.end_date || '',
    capital: 0,
    commission: 0,
    result,
    error: detail.error,
    createdAt: detail.created_at || item.created_at,
    params,
    taskType,
    radarPayload,
  };
}
