<template>
  <div ref="chartRef" :style="{ width: '100%', height: '400px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  klineData: { type: Array, default: () => [] },
  trades: { type: Array, default: () => [] },
  symbol: { type: String, default: '' },
})

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.klineData.length) return
  const data = [...props.klineData].sort((a, b) => a.date.localeCompare(b.date))
  const dates = data.map(d => d.date)
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])

  const buyPoints = props.trades
    .filter(t => t.symbol === props.symbol && t.direction === 'buy')
    .map(t => ({ coord: [t.date, t.price], symbol: 'triangle', symbolSize: 10, itemStyle: { color: '#ef5350' } }))

  const sellPoints = props.trades
    .filter(t => t.symbol === props.symbol && t.direction === 'sell')
    .map(t => ({ coord: [t.date, t.price], symbol: 'diamond', symbolSize: 10, itemStyle: { color: '#26a69a' } }))

  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: dates },
    yAxis: { scale: true },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { type: 'slider' }],
    series: [{
      type: 'candlestick', data: ohlc,
      itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' },
      markPoint: { data: [...buyPoints, ...sellPoints] },
    }],
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => [props.klineData, props.trades], render, { deep: true })
</script>
