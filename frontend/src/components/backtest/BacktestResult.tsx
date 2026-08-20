import type React from 'react';
import { useRef, useState } from 'react';
import { cn } from '../../utils/cn';
import { Badge, Button } from '../common';
import { buildTradesFilename, exportTradesToXlsx } from '../../utils/exportTradesXlsx';
import { buildMergedTradeRows } from '../../utils/buildMergedTradeRows';
import { buildPositionSummary } from '../../utils/buildPositionSummary';
import type { BacktestTask } from './BacktestAnalysis';
import { marketLabel } from '../../utils/marketLabel';
import { portfolioApi } from '../../api/portfolio';

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
  const [binding, setBinding] = useState(false);
  const [bindingMessage, setBindingMessage] = useState<string | null>(null);
  const isCompleted = task?.status === 'completed' || String(task?.status) === 'success';
  const isExecutionBound = task?.executionStatus === 'active';

  const handleCreateStrategyAccount = async () => {
    if (!task || !isCompleted) return;
    try {
      setBinding(true);
      setBindingMessage(null);
      const market = String(task.market || 'A').toUpperCase();
      await portfolioApi.createAccount({
        name: `${task.strategyName}策略账户`,
        market: market === 'HK' ? 'hk' : market === 'US' ? 'us' : 'cn',
        baseCurrency: market === 'HK' ? 'HKD' : market === 'US' ? 'USD' : 'CNY',
        strategyTaskId: task.taskId,
      });
      setBindingMessage('策略账户已创建并绑定，可在持仓页查看目标执行状态。');
    } catch (err) {
      setBindingMessage(err instanceof Error ? err.message : '创建策略账户失败');
    } finally {
      setBinding(false);
    }
  };

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
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="min-w-0">
          <h3 className="text-lg font-semibold text-foreground">{task.strategyName}</h3>
          <p className="mt-0.5 text-xs text-secondary-text">
            {task.symbol || marketLabel(task.market)} · {task.period} · {task.startDate} ~ {task.endDate}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {isExecutionBound ? (
            <span className="text-xs text-secondary-text">已绑定策略账户</span>
          ) : isCompleted ? (
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() => void handleCreateStrategyAccount()}
              disabled={binding}
            >
              {binding ? '创建中...' : '创建并绑定策略账户'}
            </button>
          ) : null}
          <Badge variant={returnTone === 'success' ? 'success' : 'danger'} size="md">
            {formatPct(result.totalReturn)}
          </Badge>
        </div>
      </div>
      {bindingMessage ? <p className="text-xs text-secondary-text">{bindingMessage}</p> : null}

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

      {/* Merged Buy/Sell Detail Table */}
      {(() => {
        const mergedRows = buildMergedTradeRows(result.rawBuys || [], result.trades || []);
        if (mergedRows.length === 0) return null;
        const buyCount = mergedRows.filter((r) => r.side === 'buy').length;
        const sellCount = mergedRows.length - buyCount;
        return (
          <div className="rounded-2xl border border-border/40 bg-card/50 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-sm font-medium text-secondary-text">
                交易明细 <span className="text-muted-text">(买 {buyCount} 笔 / 卖 {sellCount} 笔)</span>
              </h4>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  exportTradesToXlsx(
                    mergedRows,
                    buildTradesFilename({
                      strategyName: task.strategyName,
                      symbol: task.symbol,
                      market: task.market,
                      startDate: task.startDate,
                      endDate: task.endDate,
                    }),
                  )
                }
                aria-label="导出交易明细到 Excel"
              >
                导出 Excel
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border/30 text-left text-secondary-text">
                    <th className="px-2 py-2">股票</th>
                    <th className="px-2 py-2">方向</th>
                    <th className="px-2 py-2">日期</th>
                    <th className="px-2 py-2 text-right">价格</th>
                    <th className="px-2 py-2 text-right">数量</th>
                    <th className="px-2 py-2 text-right">盈亏</th>
                    <th className="px-2 py-2 text-right">收益率</th>
                    <th className="px-2 py-2 text-right">持仓天数</th>
                  </tr>
                </thead>
                <tbody>
                  {mergedRows.map((r, idx) => (
                    <tr key={idx} className="border-b border-border/20 hover:bg-hover/30">
                      <td className="px-2 py-2 font-mono">{r.symbol}</td>
                      <td className="px-2 py-2">
                        <Badge variant={r.side === 'buy' ? 'default' : 'success'}>
                          {r.side === 'buy' ? '买' : '卖'}
                        </Badge>
                      </td>
                      <td className="px-2 py-2 tabular-nums">{r.date}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.price.toFixed(3)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{r.shares.toLocaleString()}</td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right tabular-nums',
                          r.pnl == null ? 'text-muted-text' : r.pnl >= 0 ? 'text-success' : 'text-danger',
                        )}
                      >
                        {r.pnl == null ? '-' : `${r.pnl >= 0 ? '+' : ''}${r.pnl.toFixed(2)}`}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right tabular-nums',
                          r.pnlPct == null ? 'text-muted-text' : r.pnlPct >= 0 ? 'text-success' : 'text-danger',
                        )}
                      >
                        {r.pnlPct == null ? '-' : `${r.pnlPct >= 0 ? '+' : ''}${(r.pnlPct * 100).toFixed(2)}%`}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {r.holdDays == null ? '-' : r.holdDays.toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {/* Position Summary (per-symbol) */}
      {(() => {
        const summary = buildPositionSummary(
          result.rawBuys || [],
          result.trades || [],
          result.endPrices || {},
        );
        if (summary.length === 0) return null;
        return (
          <div className="rounded-2xl border border-border/40 bg-card/50 p-4">
            <h4 className="mb-3 text-sm font-medium text-secondary-text">
              持仓汇总 <span className="text-muted-text">({summary.length} 只)</span>
            </h4>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border/30 text-left text-secondary-text">
                    <th className="px-2 py-2">股票</th>
                    <th className="px-2 py-2 text-right">持仓</th>
                    <th className="px-2 py-2 text-right">成本</th>
                    <th className="px-2 py-2 text-right">当前价</th>
                    <th className="px-2 py-2 text-right">已实现盈亏</th>
                    <th className="px-2 py-2 text-right">未实现盈亏</th>
                    <th className="px-2 py-2 text-right">总盈亏</th>
                    <th className="px-2 py-2 text-right">总收益率</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.map((s, idx) => (
                    <tr key={idx} className="border-b border-border/20 hover:bg-hover/30">
                      <td className="px-2 py-2 font-mono">{s.symbol}</td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {s.shares > 0 ? s.shares.toLocaleString() : <span className="text-muted-text">0</span>}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {s.shares > 0 ? s.avgCost.toFixed(3) : <span className="text-muted-text">-</span>}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {s.currentPrice == null ? <span className="text-muted-text">-</span> : s.currentPrice.toFixed(3)}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right tabular-nums',
                          s.realizedPnl === 0 ? '' : s.realizedPnl > 0 ? 'text-success' : 'text-danger',
                        )}
                      >
                        {s.realizedPnl > 0 ? '+' : ''}{s.realizedPnl.toFixed(2)}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right tabular-nums',
                          s.unrealizedPnl === 0 ? 'text-muted-text' : s.unrealizedPnl > 0 ? 'text-success' : 'text-danger',
                        )}
                      >
                        {s.shares > 0
                          ? `${s.unrealizedPnl > 0 ? '+' : ''}${s.unrealizedPnl.toFixed(2)}`
                          : '0.00'}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right tabular-nums font-medium',
                          s.totalPnl === 0 ? '' : s.totalPnl > 0 ? 'text-success' : 'text-danger',
                        )}
                      >
                        {s.totalPnl > 0 ? '+' : ''}{s.totalPnl.toFixed(2)}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right tabular-nums',
                          s.totalReturn === 0 ? '' : s.totalReturn > 0 ? 'text-success' : 'text-danger',
                        )}
                      >
                        {s.totalReturn > 0 ? '+' : ''}{(s.totalReturn * 100).toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}
    </div>
  );
};

function formatValue(v: number): string {
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(2);
}

const EquityCurveChart: React.FC<{ data: { date: string; value: number }[] }> = ({ data }) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

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
  const xOf = (i: number) => padding.left + (i / denom) * chartW;
  const yOf = (v: number) => padding.top + chartH - ((v - min) / range) * chartH;
  const points = data.map((d, i) => `${xOf(i)},${yOf(d.value)}`);
  // 单点情况:横向延伸成一段水平线,避免 SVG path 失败
  if (data.length === 1) {
    points.push(`${padding.left + chartW},${points[0].split(',')[1]}`);
  }

  const pathD = `M ${points.join(' L ')}`;
  const areaD = `${pathD} L ${padding.left + chartW},${padding.top + chartH} L ${padding.left},${padding.top + chartH} Z`;

  // 鼠标 client 坐标 → SVG viewBox 坐标 → 最近数据点索引
  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    // viewBox 横向无 letterbox 时:rect.width 映射 width;有时让 SVG 自适应,这里近似按比例
    const vbX = ((e.clientX - rect.left) / rect.width) * width;
    if (vbX < padding.left || vbX > padding.left + chartW) {
      setHoverIdx(null);
      return;
    }
    const ratio = (vbX - padding.left) / chartW;
    const idx = Math.round(ratio * denom);
    setHoverIdx(Math.max(0, Math.min(data.length - 1, idx)));
  };
  const handleLeave = () => setHoverIdx(null);

  const hover = hoverIdx != null ? data[hoverIdx] : null;
  const hoverX = hoverIdx != null ? xOf(hoverIdx) : 0;
  const hoverY = hover ? yOf(hover.value) : 0;
  // tooltip 锚点贴近指针,过右时左翻防溢出
  const tipW = 150;
  const tipH = 44;
  const tipX = hoverX + tipW + 10 > width ? hoverX - tipW - 10 : hoverX + 10;
  const tipY = Math.max(padding.top, Math.min(hoverY - tipH / 2, height - tipH - padding.bottom));

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      className="h-full w-full"
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
    >
      <defs>
        <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.3" />
          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill="url(#equityGrad)" />
      <path d={pathD} fill="none" stroke="hsl(var(--primary))" strokeWidth="2" />
      {/* X-axis labels —— 用 currentColor + 显式 fontSize,Tailwind 的 fill-* 在 v4 不绑定 --text-* 变量,容易渲染成黑色 */}
      <g fill="currentColor" fontSize="11" className="text-secondary-text">
        {Array.from(new Set([0, Math.floor(data.length / 2), data.length - 1])).map(i => (
          <text
            key={`x-${i}`}
            x={padding.left + (i / denom) * chartW}
            y={height - 5}
            textAnchor="middle"
          >
            {data[i].date}
          </text>
        ))}
        {[min, (min + max) / 2, max].map((v, i) => (
          <text
            key={`y-${i}`}
            x={padding.left - 5}
            y={padding.top + chartH - (i / 2) * chartH}
            textAnchor="end"
            dominantBaseline="middle"
          >
            {v >= 10000 ? `${(v / 10000).toFixed(1)}万` : v.toFixed(0)}
          </text>
        ))}
      </g>
      {/* Hover guide + dot + tooltip */}
      {hover && (
        <g pointerEvents="none">
          <line
            x1={hoverX}
            x2={hoverX}
            y1={padding.top}
            y2={padding.top + chartH}
            stroke="currentColor"
            strokeOpacity="0.3"
            strokeDasharray="4 3"
            className="text-secondary-text"
          />
          <circle cx={hoverX} cy={hoverY} r="4" fill="hsl(var(--primary))" stroke="white" strokeWidth="1.5" />
          <rect
            x={tipX}
            y={tipY}
            width={tipW}
            height={tipH}
            rx="6"
            fill="hsl(var(--card))"
            stroke="hsl(var(--border))"
            strokeOpacity="0.6"
          />
          <text x={tipX + 8} y={tipY + 17} fontSize="11" fill="currentColor" className="text-secondary-text">
            {hover.date}
          </text>
          <text x={tipX + 8} y={tipY + 35} fontSize="13" fontWeight="600" fill="hsl(var(--primary))">
            {formatValue(hover.value)}
          </text>
        </g>
      )}
    </svg>
  );
};

export default BacktestResult;
