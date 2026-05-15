import { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries, HistogramSeries, type IChartApi, type ISeriesApi, type CandlestickData, type HistogramData, ColorType } from 'lightweight-charts';

export interface KlineDataPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  preclose?: number;
  volume: number;
  amount?: number;
  turn?: number;
  pctChg?: number;
}

interface KlineChartProps {
  data: KlineDataPoint[];
  className?: string;
}

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
  return v.toFixed(0);
}

function formatAmount(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
  return v.toFixed(2);
}

export function KlineChart({ data, className }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const dataMapRef = useRef<Map<string, KlineDataPoint>>(new Map());
  const [hoverData, setHoverData] = useState<KlineDataPoint | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) {
        setHoverData(null);
        return;
      }
      const timeStr = param.time as string;
      const point = dataMapRef.current.get(timeStr);
      setHoverData(point || null);
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !data.length) return;

    const map = new Map<string, KlineDataPoint>();
    const candleData: CandlestickData[] = data.map(d => {
      map.set(d.date, d);
      return { time: d.date, open: d.open, high: d.high, low: d.low, close: d.close };
    });

    const volumeData: HistogramData[] = data.map(d => ({
      time: d.date,
      value: d.volume,
      color: d.close >= d.open ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)',
    }));

    dataMapRef.current = map;
    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
    chartRef.current?.timeScale().fitContent();
    setHoverData(null);
  }, [data]);

  const d = hoverData;
  const change = d && d.preclose ? d.close - d.preclose : null;
  const pctChg = d?.pctChg ?? (d && d.preclose ? ((d.close - d.preclose) / d.preclose * 100) : null);

  const changeColor = change === null ? '' : change > 0 ? 'text-danger' : change < 0 ? 'text-success' : 'text-primary-text';
  const priceColor = d ? (d.close > d.open ? 'text-danger' : d.close < d.open ? 'text-success' : 'text-primary-text') : '';

  return (
    <div className={`relative ${className || ''}`} style={{ width: '100%', height: '100%' }}>
      {d && (
        <div className="absolute top-2 left-2 z-10 flex flex-wrap gap-x-4 gap-y-0.5 text-xs pointer-events-none">
          <span className="text-secondary-text">{d.date}</span>
          <span>开 <span className={priceColor}>{d.open.toFixed(2)}</span></span>
          <span>收 <span className={priceColor}>{d.close.toFixed(2)}</span></span>
          <span>高 <span className={priceColor}>{d.high.toFixed(2)}</span></span>
          <span>低 <span className={priceColor}>{d.low.toFixed(2)}</span></span>
          {change !== null && (
            <span>涨跌额 <span className={changeColor}>{change > 0 ? '+' : ''}{change.toFixed(2)}</span></span>
          )}
          {pctChg !== null && (
            <span>涨跌幅 <span className={changeColor}>{pctChg > 0 ? '+' : ''}{pctChg.toFixed(2)}%</span></span>
          )}
          <span>成交量 <span className="text-primary-text">{formatVolume(d.volume)}</span></span>
          {d.amount != null && d.amount > 0 && (
            <span>成交额 <span className="text-primary-text">{formatAmount(d.amount)}</span></span>
          )}
          {d.turn != null && d.turn > 0 && (
            <span>换手率 <span className="text-primary-text">{d.turn.toFixed(2)}%</span></span>
          )}
        </div>
      )}
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
