<template>
  <div ref="chartRef" :style="{ width: '100%', height: '350px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  snapshots: { type: Array, default: () => [] },
})

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.snapshots.length) return
  chart.setOption({
    title: { text: '收益曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 30 }],
    series: [{
      type: 'line',
      data: props.snapshots.map(s => [s.date, s.total_value]),
      symbol: 'none',
      lineStyle: { width: 1.5 },
      areaStyle: { opacity: 0.1 },
    }],
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => props.snapshots, render, { deep: true })
</script>
