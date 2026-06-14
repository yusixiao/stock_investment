import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, type IChartApi, type ISeriesApi, type CandlestickData, type HistogramData, type LineData, ColorType } from 'lightweight-charts';

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

export interface MacdDataPoint {
  date: string;
  dif: number;
  dea: number;
  macd: number;
}

export interface VolMaDataPoint {
  date: string;
  vol_ma5: number | null;
  vol_ma10: number | null;
}

export interface PriceMaDataPoint {
  date: string;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
}

const MA_CONFIGS = [
  { key: 'ma5', label: 'MA5', color: '#f59e0b' },
  { key: 'ma10', label: 'MA10', color: '#8b5cf6' },
  { key: 'ma20', label: 'MA20', color: '#06b6d4' },
  { key: 'ma30', label: 'MA30', color: '#10b981' },
  { key: 'ma60', label: 'MA60', color: '#ec4899' },
] as const;

type MaKey = typeof MA_CONFIGS[number]['key'];

interface KlineChartProps {
  data: KlineDataPoint[];
  macd?: MacdDataPoint[];
  volMa?: VolMaDataPoint[];
  priceMa?: PriceMaDataPoint[];
  className?: string;
}

function formatVolume(v: number, unit = ''): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿' + unit;
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万' + unit;
  return v.toFixed(0) + unit;
}

function formatAmount(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
  return v.toFixed(2);
}

export function KlineChart({ data, macd, volMa, priceMa, className }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const volMa5SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const volMa10SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const macdBarSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const difSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const deaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const priceMaSeriesRef = useRef<Record<MaKey, ISeriesApi<'Line'> | null>>({
    ma5: null, ma10: null, ma20: null, ma30: null, ma60: null,
  });
  const dataMapRef = useRef<Map<string, KlineDataPoint>>(new Map());
  const macdMapRef = useRef<Map<string, MacdDataPoint>>(new Map());
  const volMaMapRef = useRef<Map<string, VolMaDataPoint>>(new Map());
  const priceMaMapRef = useRef<Map<string, PriceMaDataPoint>>(new Map());
  const [hoverData, setHoverData] = useState<KlineDataPoint | null>(null);
  const [hoverMacd, setHoverMacd] = useState<MacdDataPoint | null>(null);
  const [hoverVolMa, setHoverVolMa] = useState<VolMaDataPoint | null>(null);
  const [hoverPriceMa, setHoverPriceMa] = useState<PriceMaDataPoint | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const [volPaneTop, setVolPaneTop] = useState<number | null>(null);
  const [macdPaneTop, setMacdPaneTop] = useState<number | null>(null);
  const [maVisible, setMaVisible] = useState<Record<MaKey, boolean>>({
    ma5: true, ma10: true, ma20: true, ma30: true, ma60: true,
  });

  const toggleMa = useCallback((key: MaKey) => {
    setMaVisible(prev => {
      const next = { ...prev, [key]: !prev[key] };
      const series = priceMaSeriesRef.current[key];
      if (series) {
        series.applyOptions({ visible: next[key] });
      }
      return next;
    });
  }, []);

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
      leftPriceScale: { borderColor: 'rgba(255,255,255,0.1)', visible: false },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)', visible: true },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
    });

    // Pane 0: K线
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 0);

    // Pane 0: 价格均线
    const maSeriesMap: Record<MaKey, ISeriesApi<'Line'>> = {} as any;
    for (const cfg of MA_CONFIGS) {
      const s = chart.addSeries(LineSeries, {
        color: cfg.color,
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        priceScaleId: 'right',
      }, 0);
      maSeriesMap[cfg.key] = s;
    }
    priceMaSeriesRef.current = maSeriesMap;

    // Pane 1: 成交量
    chart.addPane();
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 1);

    const volMa5Series = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 1);

    const volMa10Series = chart.addSeries(LineSeries, {
      color: '#8b5cf6',
      lineWidth: 1,
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 1);

    // Pane 2: MACD
    chart.addPane();
    const macdBarSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 2);

    const difSeries = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 2);

    const deaSeries = chart.addSeries(LineSeries, {
      color: '#8b5cf6',
      lineWidth: 1,
      priceFormat: { type: 'price', precision: 4, minMove: 0.0001 },
      lastValueVisible: false,
      priceLineVisible: false,
      priceScaleId: 'right',
    }, 2);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) {
        setTooltipPos(null);
        return;
      }
      const timeStr = param.time as string;
      setHoverData(dataMapRef.current.get(timeStr) || null);
      setHoverMacd(macdMapRef.current.get(timeStr) || null);
      setHoverVolMa(volMaMapRef.current.get(timeStr) || null);
      setHoverPriceMa(priceMaMapRef.current.get(timeStr) || null);
      setTooltipPos({ x: param.point.x, y: param.point.y });
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    volMa5SeriesRef.current = volMa5Series;
    volMa10SeriesRef.current = volMa10Series;
    macdBarSeriesRef.current = macdBarSeries;
    difSeriesRef.current = difSeries;
    deaSeriesRef.current = deaSeries;

    const updateLayout = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
      try {
        const pane0 = chart.paneSize(0);
        const pane1 = chart.paneSize(1);
        setVolPaneTop(pane0.height);
        setMacdPaneTop(pane0.height + pane1.height);
      } catch { /* pane not ready */ }
    };

    const resizeObserver = new ResizeObserver(updateLayout);
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
      color: d.close >= d.open ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)',
    }));

    dataMapRef.current = map;
    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
    const totalBars = candleData.length;
    if (totalBars > 150) {
      chartRef.current?.timeScale().setVisibleLogicalRange({ from: totalBars - 150, to: totalBars - 1 });
    } else {
      chartRef.current?.timeScale().fitContent();
    }
    const lastPoint = data[data.length - 1];
    setHoverData(lastPoint || null);
  }, [data]);

  useEffect(() => {
    if (!macdBarSeriesRef.current || !difSeriesRef.current || !deaSeriesRef.current || !macd?.length) return;

    const macdMap = new Map<string, MacdDataPoint>();
    const barData: HistogramData[] = macd.map(d => {
      macdMap.set(d.date, d);
      return {
        time: d.date,
        value: d.macd,
        color: d.macd >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)',
      };
    });

    const difData: LineData[] = macd.map(d => ({ time: d.date, value: d.dif }));
    const deaData: LineData[] = macd.map(d => ({ time: d.date, value: d.dea }));

    macdMapRef.current = macdMap;
    macdBarSeriesRef.current.setData(barData);
    difSeriesRef.current.setData(difData);
    deaSeriesRef.current.setData(deaData);
    const lastMacd = macd[macd.length - 1];
    setHoverMacd(lastMacd || null);
  }, [macd]);

  useEffect(() => {
    if (!volMa5SeriesRef.current || !volMa10SeriesRef.current || !volMa?.length) return;

    const map = new Map<string, VolMaDataPoint>();
    const ma5Data: LineData[] = [];
    const ma10Data: LineData[] = [];

    for (const d of volMa) {
      map.set(d.date, d);
      if (d.vol_ma5 != null) ma5Data.push({ time: d.date, value: d.vol_ma5 });
      if (d.vol_ma10 != null) ma10Data.push({ time: d.date, value: d.vol_ma10 });
    }

    volMaMapRef.current = map;
    volMa5SeriesRef.current.setData(ma5Data);
    volMa10SeriesRef.current.setData(ma10Data);
    const lastVolMa = volMa[volMa.length - 1];
    setHoverVolMa(lastVolMa || null);
  }, [volMa]);

  useEffect(() => {
    if (!priceMa?.length) return;

    const map = new Map<string, PriceMaDataPoint>();
    const seriesData: Record<MaKey, LineData[]> = {
      ma5: [], ma10: [], ma20: [], ma30: [], ma60: [],
    };

    for (const d of priceMa) {
      map.set(d.date, d);
      for (const cfg of MA_CONFIGS) {
        const val = d[cfg.key];
        if (val != null) seriesData[cfg.key].push({ time: d.date, value: val });
      }
    }

    priceMaMapRef.current = map;
    for (const cfg of MA_CONFIGS) {
      const series = priceMaSeriesRef.current[cfg.key];
      if (series) series.setData(seriesData[cfg.key]);
    }
    const lastPriceMa = priceMa[priceMa.length - 1];
    setHoverPriceMa(lastPriceMa || null);
  }, [priceMa]);

  const d = hoverData;
  const change = d && d.preclose ? d.close - d.preclose : null;
  const pctChg = d?.pctChg ?? (d && d.preclose ? ((d.close - d.preclose) / d.preclose * 100) : null);

  const changeColor = change === null ? '' : change > 0 ? 'text-danger' : change < 0 ? 'text-success' : 'text-primary-text';
  const priceColor = d ? (d.close > d.open ? 'text-danger' : d.close < d.open ? 'text-success' : 'text-primary-text') : '';

  return (
    <div className={`relative ${className || ''}`} style={{ width: '100%', height: '100%' }}>
      <div className="absolute top-1 left-2 z-10 flex gap-x-3 text-xs pointer-events-auto">
        <span className="text-secondary-text">均线</span>
        {MA_CONFIGS.map(cfg => {
          const val = hoverPriceMa?.[cfg.key];
          return (
            <span
              key={cfg.key}
              onClick={() => toggleMa(cfg.key)}
              className={`cursor-pointer select-none ${!maVisible[cfg.key] ? 'opacity-30 line-through' : ''}`}
              style={{ color: cfg.color }}
            >
              {cfg.label} {val != null ? val.toFixed(2) : '——'}
            </span>
          );
        })}
      </div>
      {d && tooltipPos && (
        <div
          className="absolute z-20 pointer-events-none rounded bg-[rgba(20,20,30,0.88)] px-2.5 py-2 text-xs leading-relaxed shadow-lg border border-white/10"
          style={{ left: tooltipPos.x + 16, top: tooltipPos.y + 16 }}
        >
          <div className="text-secondary-text mb-1">{d.date}</div>
          <div className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
            <span className="text-secondary-text">开</span><span className={priceColor}>{d.open.toFixed(2)}</span>
            <span className="text-secondary-text">收</span><span className={priceColor}>{d.close.toFixed(2)}</span>
            <span className="text-secondary-text">高</span><span className={priceColor}>{d.high.toFixed(2)}</span>
            <span className="text-secondary-text">低</span><span className={priceColor}>{d.low.toFixed(2)}</span>
            {change !== null && (
              <><span className="text-secondary-text">涨跌额</span><span className={changeColor}>{change > 0 ? '+' : ''}{change.toFixed(2)}</span></>
            )}
            {pctChg !== null && (
              <><span className="text-secondary-text">涨跌幅</span><span className={changeColor}>{pctChg > 0 ? '+' : ''}{pctChg.toFixed(2)}%</span></>
            )}
            <span className="text-secondary-text">成交量</span><span className="text-primary-text">{formatVolume(d.volume)}</span>
            {d.amount != null && d.amount > 0 && (
              <><span className="text-secondary-text">成交额</span><span className="text-primary-text">{formatAmount(d.amount)}</span></>
            )}
            {d.turn != null && d.turn > 0 && (
              <><span className="text-secondary-text">换手率</span><span className="text-primary-text">{d.turn.toFixed(2)}%</span></>
            )}
          </div>
        </div>
      )}
      {volPaneTop !== null && (
        <div className="absolute left-2 z-10 flex gap-x-4 text-xs pointer-events-none" style={{ top: volPaneTop + 4 }}>
          <span>VOL</span>
          {hoverVolMa?.vol_ma5 != null && (
            <span>MA5 <span className="text-[#f59e0b]">{formatVolume(hoverVolMa.vol_ma5, '股')}</span></span>
          )}
          {hoverVolMa?.vol_ma10 != null && (
            <span>MA10 <span className="text-[#8b5cf6]">{formatVolume(hoverVolMa.vol_ma10, '股')}</span></span>
          )}
        </div>
      )}
      {macdPaneTop !== null && (
        <div className="absolute left-2 z-10 flex gap-x-4 text-xs pointer-events-none" style={{ top: macdPaneTop + 4 }}>
          <span>MACD</span>
          {hoverMacd && (
            <>
              <span>DIF <span className="text-[#f59e0b]">{hoverMacd.dif.toFixed(4)}</span></span>
              <span>DEA <span className="text-[#8b5cf6]">{hoverMacd.dea.toFixed(4)}</span></span>
              <span>MACD <span className={hoverMacd.macd >= 0 ? 'text-danger' : 'text-success'}>{hoverMacd.macd.toFixed(4)}</span></span>
            </>
          )}
        </div>
      )}
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
