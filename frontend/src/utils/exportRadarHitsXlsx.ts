import * as XLSX from 'xlsx';
import type { ScanRadarPayload, ScanRadarHit } from '../api/backtestEngine';

/**
 * 导出策略雷达扫描结果为 .xlsx。
 * 因子列(factors)动态展开为独立列(各 hit 的 factor key 取并集)。
 * 与 StrategyRadar / RadarResultView 表格列结构对齐。
 */
export function exportRadarHitsToXlsx(
  payload: ScanRadarPayload | null | undefined,
  filename: string,
): void {
  const hits: ScanRadarHit[] = payload?.hits ?? [];
  if (hits.length === 0) return;

  // 因子列名并集(保留首次出现顺序)
  const factorKeys: string[] = [];
  const seen = new Set<string>();
  for (const h of hits) {
    for (const k of Object.keys(h.factors || {})) {
      if (!seen.has(k)) {
        seen.add(k);
        factorKeys.push(k);
      }
    }
  }

  const data = hits.map((h) => {
    const row: Record<string, string | number> = {
      代码: h.symbol,
      名称: h.name ?? '-',
      当前价: Number(h.current_price.toFixed(4)),
      '信号日至今(%)':
        h.change_pct_since_signal == null
          ? '-'
          : Number((h.change_pct_since_signal * 100).toFixed(2)),
      最近命中日: h.last_match_date,
      命中次数: h.match_count,
    };
    for (const k of factorKeys) {
      const v = h.factors?.[k];
      row[k] = typeof v === 'number' ? Number(v.toFixed(2)) : (v == null ? '-' : String(v));
    }
    return row;
  });

  const ws = XLSX.utils.json_to_sheet(data);
  ws['!cols'] = [
    { wch: 12 }, // 代码
    { wch: 16 }, // 名称
    { wch: 10 }, // 当前价
    { wch: 14 }, // 信号日至今
    { wch: 12 }, // 最近命中日
    { wch: 8 },  // 命中次数
    ...factorKeys.map(() => ({ wch: 12 })),
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '雷达命中');
  XLSX.writeFile(wb, filename);
}

/** 用任务信息生成默认文件名:策略名_市场_起止_雷达命中.xlsx */
export function buildRadarFilename(opts: {
  strategyName?: string;
  market?: string | null;
  startDate?: string;
  endDate?: string;
}): string {
  const safe = (s: string | null | undefined) =>
    (s || '').replace(/[\\/:*?"<>|]/g, '_').trim();
  const parts = [
    safe(opts.strategyName) || '雷达',
    safe(opts.market),
    safe(opts.startDate),
    safe(opts.endDate),
    '雷达命中',
  ].filter(Boolean);
  return `${parts.join('_')}.xlsx`;
}
