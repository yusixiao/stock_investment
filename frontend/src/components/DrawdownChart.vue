<template>
  <div ref="chartRef" :style="{ width: '100%', height: '200px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({ equityCurve: { type: Array, default: () => [] } })

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.equityCurve.length) return
  const values = props.equityCurve.map(d => d.total_value)
  let peak = values[0]
  const drawdowns = values.map((v, i) => {
    if (v > peak) peak = v
    const dd = peak > 0 ? -((peak - v) / peak) * 100 : 0
    return [props.equityCurve[i].date, dd]
  })
  chart.setOption({
    title: { text: '回撤曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', formatter: p => `${p[0].axisValue}<br/>回撤: ${p[0].value.toFixed(2)}%` },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'line', data: drawdowns, areaStyle: { color: 'rgba(239,83,80,0.15)' }, lineStyle: { color: '#ef5350', width: 1 }, symbol: 'none' }],
    dataZoom: [{ type: 'inside' }],
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => props.equityCurve, render, { deep: true })
</script>
