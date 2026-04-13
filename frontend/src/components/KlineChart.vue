<template>
  <div ref="chartRef" :style="{ width: '100%', height: height + 'px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  klineData: { type: Array, default: () => [] },
  indicators: { type: Object, default: () => ({}) },
  height: { type: Number, default: 700 },
})

const chartRef = ref(null)
let chart = null

function buildOption() {
  const data = [...props.klineData].sort((a, b) => a.date.localeCompare(b.date))
  const dates = data.map(d => d.date)
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
  const volumes = data.map(d => d.volume)
  const colors = data.map(d => (d.close >= d.open ? '#ef5350' : '#26a69a'))

  const hasSubChart = props.indicators.macd || props.indicators.kdj
  const gridHeight = hasSubChart ? '45%' : '55%'

  const grids = [
    { left: '8%', right: '3%', top: '5%', height: gridHeight },
    { left: '8%', right: '3%', top: hasSubChart ? '53%' : '63%', height: '12%' },
  ]
  const xAxes = [
    { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
    { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
  ]
  const yAxes = [
    { scale: true, gridIndex: 0 },
    { scale: true, gridIndex: 1, splitNumber: 2 },
  ]
  const series = [
    { name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0, itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' } },
    { name: '成交量', type: 'bar', data: volumes.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })), xAxisIndex: 1, yAxisIndex: 1 },
  ]

  let subGridIdx = 2

  if (props.indicators.ma) {
    const maData = [...props.indicators.ma].sort((a, b) => a.date.localeCompare(b.date))
    const maColors = { ma5: '#ff9800', ma10: '#2196f3', ma20: '#9c27b0', ma60: '#4caf50' }
    for (const key of ['ma5', 'ma10', 'ma20', 'ma60']) {
      series.push({
        name: key.toUpperCase(), type: 'line', data: maData.map(d => d[key]),
        xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none',
        lineStyle: { width: 1, color: maColors[key] },
      })
    }
  }

  if (props.indicators.boll) {
    const bollData = [...props.indicators.boll].sort((a, b) => a.date.localeCompare(b.date))
    for (const [key, color] of [['boll_upper', '#e91e63'], ['boll_mid', '#ff9800'], ['boll_lower', '#2196f3']]) {
      series.push({
        name: key, type: 'line', data: bollData.map(d => d[key]),
        xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none',
        lineStyle: { width: 1, color, type: key === 'boll_mid' ? 'solid' : 'dashed' },
      })
    }
  }

  if (props.indicators.macd) {
    const macdData = [...props.indicators.macd].sort((a, b) => a.date.localeCompare(b.date))
    const top = `${parseInt(grids[1].top) + 15}%`
    grids.push({ left: '8%', right: '3%', top, height: '12%' })
    xAxes.push({ type: 'category', data: dates, gridIndex: subGridIdx, axisLabel: { show: false } })
    yAxes.push({ scale: true, gridIndex: subGridIdx, splitNumber: 2 })
    series.push(
      { name: 'DIF', type: 'line', data: macdData.map(d => d.dif), xAxisIndex: subGridIdx, yAxisIndex: subGridIdx, symbol: 'none', lineStyle: { width: 1, color: '#ff9800' } },
      { name: 'DEA', type: 'line', data: macdData.map(d => d.dea), xAxisIndex: subGridIdx, yAxisIndex: subGridIdx, symbol: 'none', lineStyle: { width: 1, color: '#2196f3' } },
      { name: 'MACD', type: 'bar', data: macdData.map(d => ({ value: d.macd, itemStyle: { color: d.macd >= 0 ? '#ef5350' : '#26a69a' } })), xAxisIndex: subGridIdx, yAxisIndex: subGridIdx },
    )
    subGridIdx++
  }

  if (props.indicators.kdj) {
    const kdjData = [...props.indicators.kdj].sort((a, b) => a.date.localeCompare(b.date))
    const prevTop = grids[grids.length - 1]
    const top = `${parseInt(prevTop.top) + parseInt(prevTop.height) + 3}%`
    grids.push({ left: '8%', right: '3%', top, height: '12%' })
    xAxes.push({ type: 'category', data: dates, gridIndex: subGridIdx })
    yAxes.push({ scale: true, gridIndex: subGridIdx, splitNumber: 2 })
    series.push(
      { name: 'K', type: 'line', data: kdjData.map(d => d.k), xAxisIndex: subGridIdx, yAxisIndex: subGridIdx, symbol: 'none', lineStyle: { width: 1, color: '#ff9800' } },
      { name: 'D', type: 'line', data: kdjData.map(d => d.d), xAxisIndex: subGridIdx, yAxisIndex: subGridIdx, symbol: 'none', lineStyle: { width: 1, color: '#2196f3' } },
      { name: 'J', type: 'line', data: kdjData.map(d => d.j), xAxisIndex: subGridIdx, yAxisIndex: subGridIdx, symbol: 'none', lineStyle: { width: 1, color: '#9c27b0' } },
    )
    subGridIdx++
  }

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    dataZoom: [
      { type: 'inside', xAxisIndex: xAxes.map((_, i) => i), start: 70, end: 100 },
      { type: 'slider', xAxisIndex: xAxes.map((_, i) => i), bottom: '2%', start: 70, end: 100 },
    ],
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series,
  }
}

function renderChart() {
  if (!chart || !props.klineData.length) return
  chart.setOption(buildOption(), true)
}

const handleResize = () => chart?.resize()

onMounted(() => {
  chart = echarts.init(chartRef.value)
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  chart?.dispose()
  window.removeEventListener('resize', handleResize)
})

watch(() => [props.klineData, props.indicators], renderChart, { deep: true })
</script>
