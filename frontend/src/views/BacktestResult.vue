<template>
  <div class="backtest-result-page">
    <div class="header">
      <button @click="$router.push('/backtest')">返回回测</button>
      <h1>回测结果</h1>
    </div>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="result">
      <MetricCards :metrics="result.metrics" />
      <EquityCurve :curves="[{ name: '策略', data: result.equity_curve }]" />
      <DrawdownChart :equityCurve="result.equity_curve" />
      <TradeTable :trades="result.trades" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchBacktestResult } from '../api'
import MetricCards from '../components/MetricCards.vue'
import EquityCurve from '../components/EquityCurve.vue'
import DrawdownChart from '../components/DrawdownChart.vue'
import TradeTable from '../components/TradeTable.vue'

const route = useRoute()
const taskId = route.params.id
const result = ref(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await fetchBacktestResult(taskId)
    if (data.status === 'success') {
      result.value = data.result
    } else if (data.status === 'failed') {
      error.value = data.error || '回测失败'
    } else {
      error.value = '回测尚未完成'
    }
  } catch (e) {
    error.value = '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.backtest-result-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.header button { padding: 6px 12px; cursor: pointer; }
.loading, .error { text-align: center; padding: 40px; color: #909399; }
.error { color: #f56c6c; }
</style>
