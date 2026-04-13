<template>
  <div ref="chartRef" :style="{ width: '100%', height: '350px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  curves: { type: Array, default: () => [] },
})

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.curves.length) return
  const series = props.curves.map((c, i) => ({
    name: c.name || `策略${i + 1}`,
    type: 'line',
    data: c.data.map(d => [d.date, d.total_value]),
    symbol: 'none',
    lineStyle: { width: 1.5 },
  }))
  chart.setOption({
    title: { text: '收益曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 30 }],
    series,
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => props.curves, render, { deep: true })
</script>
