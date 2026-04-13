<template>
  <div class="backtest-result-page">
    <div class="header">
      <button @click="$router.push('/backtest')">返回回测</button>
      <h1>回测结果</h1>
      <button v-if="result && result.equity_curve" class="btn-import" @click="showImport = true">导入持仓</button>
    </div>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="result && result.screened_symbols">
      <h2>选股回测结果 ({{ result.screened_symbols.length }} 只)</h2>
      <table class="result-table" v-if="result.screened_symbols.length">
        <thead>
          <tr><th>股票代码</th><th>匹配次数</th><th>匹配日期</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in result.screened_symbols" :key="item.symbol">
            <td>
              <span class="symbol-link" @click="$router.push('/stock/' + item.symbol)">{{ item.symbol }}</span>
            </td>
            <td>{{ item.match_dates.length }}</td>
            <td class="dates-cell">
              <span v-for="(d, i) in item.match_dates" :key="d" class="date-tag">{{ d }}<span v-if="i < item.match_dates.length - 1">、</span></span>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">无匹配结果</div>
    </div>
    <div v-else-if="result">
      <MetricCards :metrics="result.metrics" />
      <EquityCurve :curves="[{ name: '策略', data: result.equity_curve }]" />
      <DrawdownChart :equityCurve="result.equity_curve" />
      <TradeTable :trades="result.trades" />
    </div>

    <div v-if="showImport" class="import-overlay" @click.self="showImport = false">
      <div class="import-form">
        <h3>导入持仓为新组合</h3>
        <input v-model="importName" placeholder="组合名称" class="input" />
        <div class="import-actions">
          <button class="btn-primary" @click="onImport">确认导入</button>
          <button class="btn-secondary" @click="showImport = false">取消</button>
        </div>
        <div v-if="importError" class="import-error">{{ importError }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchBacktestResult, importFromBacktest } from '../api'
import MetricCards from '../components/MetricCards.vue'
import EquityCurve from '../components/EquityCurve.vue'
import DrawdownChart from '../components/DrawdownChart.vue'
import TradeTable from '../components/TradeTable.vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id
const result = ref(null)
const loading = ref(true)
const error = ref('')
const showImport = ref(false)
const importName = ref('')
const importError = ref('')

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

async function onImport() {
  if (!importName.value) return
  importError.value = ''
  try {
    const { data } = await importFromBacktest(taskId, { name: importName.value })
    showImport.value = false
    router.push(`/portfolio/${data.id}`)
  } catch (e) {
    importError.value = e.response?.data?.detail || '导入失败'
  }
}
</script>

<style scoped>
.backtest-result-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.header h1 { flex: 1; }
.header button { padding: 6px 12px; cursor: pointer; }
.btn-import { background: #67c23a; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
.btn-primary { background: #409eff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-secondary { background: #dcdfe6; color: #606266; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.loading, .error { text-align: center; padding: 40px; color: #909399; }
.error { color: #f56c6c; }
.result-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 12px; }
.result-table th { text-align: left; padding: 10px 8px; border-bottom: 2px solid #ebeef5; color: #909399; font-weight: normal; }
.result-table td { padding: 10px 8px; border-bottom: 1px solid #ebeef5; }
.symbol-link { color: #409eff; cursor: pointer; font-weight: bold; }
.symbol-link:hover { text-decoration: underline; }
.dates-cell { max-width: 600px; }
.date-tag { font-size: 12px; color: #606266; }
.empty { text-align: center; padding: 24px; color: #909399; }
.import-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.import-form { background: white; border-radius: 8px; padding: 24px; width: 360px; }
.import-form h3 { margin: 0 0 16px; }
.input { width: 100%; padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; box-sizing: border-box; }
.import-actions { display: flex; gap: 8px; margin-top: 16px; }
.import-error { color: #f56c6c; margin-top: 8px; font-size: 13px; }
</style>
