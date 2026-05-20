import type React from 'react';
import { cn } from '../../utils/cn';
import { Badge } from '../common';
import type { BacktestTask } from './BacktestAnalysis';

interface Props {
  task: BacktestTask | null;
}

function formatPct(value: number | undefined | null): string {
  if (value == null) return '--';
  return `${(value * 100).toFixed(2)}%`;
}

function formatNumber(value: number | undefined | null, decimals = 2): string {
  if (value == null) return '--';
  return value.toFixed(decimals);
}

const StatItem: React.FC<{ label: string; value: string; tone?: 'success' | 'danger' | 'default' }> = ({
  label, value, tone = 'default',
}) => (
  <div className="flex flex-col items-center rounded-xl border border-border/40 bg-card/50 px-3 py-3">
    <span className="text-xs text-secondary-text">{label}</span>
    <span className={cn(
      'mt-1 text-lg font-semibold tabular-nums',
      tone === 'success' && 'text-success',
      tone === 'danger' && 'text-danger',
      tone === 'default' && 'text-foreground',
    )}>
      {value}
    </span>
  </div>
);

const BacktestResult: React.FC<Props> = ({ task }) => {
  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border border-dashed border-border/60 bg-card/30">
            <svg className="h-7 w-7 text-secondary-text" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <p className="text-sm text-secondary-text">选择策略并运行回测</p>
          <p className="mt-1 text-xs text-muted-text">回测结果将在这里展示</p>
        </div>
      </div>
    );
  }

  if (task.status === 'running') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-cyan/20 border-t-cyan" />
        <div className="text-center">
          <p className="text-sm text-foreground">{task.strategyName} 回测中...</p>
          {task.progressPhase && (
            <p className="mt-1 text-xs text-secondary-text">{task.progressPhase}</p>
          )}
          {task.progress != null && task.progress > 0 && (
            <div className="mt-3 w-64">
              <div className="h-1.5 overflow-hidden rounded-full bg-border/30">
                <div
                  className="h-full rounded-full bg-cyan transition-all duration-300"
                  style={{ width: `${task.progress}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-muted-text tabular-nums">{task.progress}%</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (task.status === 'failed') {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <Badge variant="danger">回测失败</Badge>
          <p className="mt-2 text-sm text-secondary-text">{task.error || '未知错误'}</p>
        </div>
      </div>
    );
  }

  const result = task.result;
  if (!result) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-secondary-text">无结果数据</p>
      </div>
    );
  }

  const returnTone = result.totalReturn >= 0 ? 'success' : 'danger';

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-foreground">{task.strategyName}</h3>
          <p className="mt-0.5 text-xs text-secondary-text">
            {task.symbol && `${task.symbol} · `}{task.market} · {task.period} · {task.startDate} ~ {task.endDate}
          </p>
        </div>
        <Badge variant={returnTone === 'success' ? 'success' : 'danger'} size="md">
          {formatPct(result.totalReturn)}
        </Badge>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        <StatItem label="总收益率" value={formatPct(result.totalReturn)} tone={returnTone} />
        <StatItem label="年化收益" value={formatPct(result.annualizedReturn)} tone={result.annualizedReturn >= 0 ? 'success' : 'danger'} />
        <StatItem label="最大回撤" value={formatPct(result.maxDrawdown)} tone="danger" />
        <StatItem label="夏普比率" value={formatNumber(result.sharpeRatio)} />
        <StatItem label="胜率" value={formatPct(result.winRate)} />
        <StatItem label="交易次数" value={result.totalTrades != null ? String(result.totalTrades) : '--'} />
        <StatItem label="盈亏比" value={formatNumber(result.profitFactor)} />
        <StatItem label="平均盈利" value={formatPct(result.avgWin)} tone="success" />
        <StatItem label="平均亏损" value={formatPct(result.avgLoss)} tone="danger" />
      </div>

      {/* Equity Curve */}
      {result.equityCurve.length > 0 && (
        <div className="rounded-2xl border border-border/40 bg-card/50 p-4">
          <h4 className="mb-3 text-sm font-medium text-secondary-text">资产走势</h4>
          <div className="h-64 w-full">
            <EquityCurveChart data={result.equityCurve} />
          </div>
        </div>
      )}

      {/* Buy Detail Table */}
      {result.rawBuys && result.rawBuys.length > 0 && (
        <div className="rounded-2xl border border-border/40 bg-card/50 p-4">
          <h4 className="mb-3 text-sm font-medium text-secondary-text">
            买入明细 <span className="text-muted-text">({result.rawBuys.length}笔)</span>
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/30 text-left text-secondary-text">
                  <th className="px-2 py-2">买入时间</th>
                  <th className="px-2 py-2">股票</th>
                  <th className="px-2 py-2 text-right">买入价格</th>
                  <th className="px-2 py-2 text-right">股数</th>
                </tr>
              </thead>
              <tbody>
                {result.rawBuys.map((b, idx) => (
                  <tr key={idx} className="border-b border-border/20 hover:bg-hover/30">
                    <td className="px-2 py-2 tabular-nums">{b.date}</td>
                    <td className="px-2 py-2 font-mono">{b.symbol}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{b.price.toFixed(3)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{b.shares.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Trade Table */}
      {result.trades.length > 0 && (
        <div className="rounded-2xl border border-border/40 bg-card/50 p-4">
          <h4 className="mb-3 text-sm font-medium text-secondary-text">
            交易明细 <span className="text-muted-text">({result.trades.length}笔)</span>
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/30 text-left text-secondary-text">
                  <th className="px-2 py-2">股票</th>
                  <th className="px-2 py-2">方向</th>
                  <th className="px-2 py-2">买入日期</th>
                  <th className="px-2 py-2">卖出日期</th>
                  <th className="px-2 py-2 text-right">买入价</th>
                  <th className="px-2 py-2 text-right">卖出价</th>
                  <th className="px-2 py-2 text-right">盈亏</th>
                  <th className="px-2 py-2 text-right">收益率</th>
                  <th className="px-2 py-2 text-right">持仓天数</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.map((trade, idx) => (
                  <tr key={idx} className="border-b border-border/20 hover:bg-hover/30">
                    <td className="px-2 py-2 font-mono">{trade.symbol}</td>
                    <td className="px-2 py-2">
                      <Badge variant={trade.direction === 'long' ? 'success' : 'danger'}>
                        {trade.direction === 'long' ? '做多' : '做空'}
                      </Badge>
                    </td>
                    <td className="px-2 py-2 tabular-nums">{trade.entryDate}</td>
                    <td className="px-2 py-2 tabular-nums">{trade.exitDate}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{trade.entryPrice.toFixed(2)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{trade.exitPrice.toFixed(2)}</td>
                    <td className={cn('px-2 py-2 text-right tabular-nums', trade.pnl >= 0 ? 'text-success' : 'text-danger')}>
                      {trade.pnl >= 0 ? '+' : ''}{trade.pnl.toFixed(2)}
                    </td>
                    <td className={cn('px-2 py-2 text-right tabular-nums', trade.pnlPct >= 0 ? 'text-success' : 'text-danger')}>
                      {trade.pnlPct >= 0 ? '+' : ''}{(trade.pnlPct * 100).toFixed(2)}%
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{trade.holdDays}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

const EquityCurveChart: React.FC<{ data: { date: string; value: number }[] }> = ({ data }) => {
  if (data.length === 0) return null;

  const values = data.map(d => d.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  // 当曲线完全平坦(无交易/资金未变动)时,人工撑开 ±5% 让线显示在中间
  let min = rawMin;
  let max = rawMax;
  if (max - min < Math.abs(max) * 1e-6) {
    const center = max || 1;
    min = center * 0.95;
    max = center * 1.05;
  }
  const range = max - min || 1;
  const width = 800;
  const height = 240;
  const padding = { top: 10, right: 10, bottom: 30, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const denom = data.length > 1 ? data.length - 1 : 1;
  const points = data.map((d, i) => {
    const x = padding.left + (i / denom) * chartW;
    const y = padding.top + chartH - ((d.value - min) / range) * chartH;
    return `${x},${y}`;
  });
  // 单点情况:横向延伸成一段水平线,避免 SVG path 失败
  if (data.length === 1) {
    points.push(`${padding.left + chartW},${points[0].split(',')[1]}`);
  }

  const pathD = `M ${points.join(' L ')}`;
  const areaD = `${pathD} L ${padding.left + chartW},${padding.top + chartH} L ${padding.left},${padding.top + chartH} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full">
      <defs>
        <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.3" />
          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill="url(#equityGrad)" />
      <path d={pathD} fill="none" stroke="hsl(var(--primary))" strokeWidth="2" />
      {/* X-axis labels */}
      {Array.from(new Set([0, Math.floor(data.length / 2), data.length - 1])).map(i => (
        <text
          key={i}
          x={padding.left + (i / denom) * chartW}
          y={height - 5}
          textAnchor="middle"
          className="fill-secondary-text text-[10px]"
        >
          {data[i].date}
        </text>
      ))}
      {/* Y-axis labels */}
      {[min, (min + max) / 2, max].map((v, i) => (
        <text
          key={i}
          x={padding.left - 5}
          y={padding.top + chartH - (i / 2) * chartH}
          textAnchor="end"
          dominantBaseline="middle"
          className="fill-secondary-text text-[10px]"
        >
          {v >= 10000 ? `${(v / 10000).toFixed(1)}万` : v.toFixed(0)}
        </text>
      ))}
    </svg>
  );
};

export default BacktestResult;
