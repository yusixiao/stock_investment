import type React from 'react';
import { cn } from '../../utils/cn';
import type { ScanRadarPayload, ScanRadarHit } from '../../api/backtestEngine';

interface Props {
  payload: ScanRadarPayload | null | undefined;
}

// 雷达扫描结果只读视图:与 StrategyRadar 实时扫描结果区相同的展示规则,
// 用于 BacktestDetail 在历史记录里复看雷达任务
const RadarResultView: React.FC<Props> = ({ payload }) => {
  if (!payload) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-secondary-text">无扫描结果数据</p>
      </div>
    );
  }
  const hits: ScanRadarHit[] = payload.hits ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-shrink-0 flex-wrap items-center gap-2 border-b border-border/30 bg-card/20 px-4 py-3 text-xs text-muted-text">
        <span>
          扫描了 {payload.total_scanned.toLocaleString()} 只股票,命中 {hits.length} 只
        </span>
        {payload.date_range && (
          <span>· 区间 {payload.date_range.start} ~ {payload.date_range.end}</span>
        )}
        {payload.data_latest_date && (
          <span>· 实际数据日 {payload.data_latest_date}</span>
        )}
        {payload.frequency && <span>· 频率 {payload.frequency}</span>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {hits.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-secondary-text">暂无命中股票</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/30 text-left text-xs text-secondary-text">
                  <th className="px-3 py-2">代码</th>
                  <th className="px-3 py-2">名称</th>
                  <th className="px-3 py-2 text-right">当前价</th>
                  <th className="px-3 py-2 text-right">信号日至今</th>
                  <th className="px-3 py-2">最近命中日</th>
                  <th className="px-3 py-2 text-right">命中次数</th>
                  <th className="px-3 py-2">关键因子值</th>
                </tr>
              </thead>
              <tbody>
                {hits.map((item) => (
                  <tr
                    key={item.symbol}
                    className="border-b border-border/20 hover:bg-hover/30"
                  >
                    <td className="px-3 py-2 font-mono">{item.symbol}</td>
                    <td className="px-3 py-2">{item.name ?? '-'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {item.current_price.toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        'px-3 py-2 text-right tabular-nums',
                        item.change_pct_since_signal == null
                          ? 'text-muted-text'
                          : item.change_pct_since_signal >= 0
                          ? 'text-success'
                          : 'text-danger',
                      )}
                    >
                      {item.change_pct_since_signal == null
                        ? '-'
                        : `${item.change_pct_since_signal >= 0 ? '+' : ''}${(item.change_pct_since_signal * 100).toFixed(2)}%`}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-secondary-text">
                      {item.last_match_date}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{item.match_count}</td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(item.factors).map(([k, v]) => (
                          <span
                            key={k}
                            className="inline-flex items-center gap-1 rounded-md border border-border/40 bg-card/40 px-2 py-0.5 text-xs"
                          >
                            <span className="text-muted-text">{k}</span>
                            <span className="tabular-nums">
                              {typeof v === 'number' ? v.toFixed(2) : String(v ?? '-')}
                            </span>
                          </span>
                        ))}
                      </div>
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

export default RadarResultView;
