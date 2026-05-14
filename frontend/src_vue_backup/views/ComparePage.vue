<template>
  <div class="compare-page">
    <h1>多策略对比</h1>
    <div class="task-list">
      <h3>选择回测结果</h3>
      <div v-for="task in tasks" :key="task.task_id" class="task-item">
        <label>
          <input type="checkbox" :value="task.task_id" v-model="selectedTasks" @change="loadSelectedResults" />
          {{ task.task_id }} ({{ task.status }}) — {{ task.created_at }}
        </label>
      </div>
      <p v-if="!tasks.length" class="empty">暂无回测结果，请先运行回测</p>
    </div>
    <div v-if="results.length">
      <EquityCurve :curves="equityCurves" />
      <h3>指标对比</h3>
      <table class="compare-table">
        <thead>
          <tr>
            <th>任务ID</th>
            <th>总收益率</th>
            <th>年化收益率</th>
            <th>最大回撤</th>
            <th>夏普比率</th>
            <th>胜率</th>
            <th>交易次数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in results" :key="r.task_id">
            <td>{{ r.task_id }}</td>
            <td>{{ pct(r.metrics.total_return) }}</td>
            <td>{{ pct(r.metrics.annualized_return) }}</td>
            <td>{{ pct(r.metrics.max_drawdown) }}</td>
            <td>{{ r.metrics.sharpe_ratio?.toFixed(2) }}</td>
            <td>{{ pct(r.metrics.win_rate) }}</td>
            <td>{{ r.metrics.trade_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { fetchBacktestResult, fetchBacktestTasks } from '../api'
import EquityCurve from '../components/EquityCurve.vue'

const tasks = ref([])
const selectedTasks = ref([])
const results = ref([])

const equityCurves = computed(() =>
  results.value.map(r => ({ name: r.task_id, data: r.equity_curve }))
)

function pct(v) { return v != null ? (v * 100).toFixed(2) + '%' : '-' }

async function loadSelectedResults() {
  results.value = []
  for (const taskId of selectedTasks.value) {
    try {
      const { data } = await fetchBacktestResult(taskId)
      if (data.status === 'success' && data.result) {
        results.value.push({ task_id: taskId, ...data.result })
      }
    } catch (e) { /* skip */ }
  }
}

onMounted(async () => {
  try {
    const { data } = await fetchBacktestTasks()
    tasks.value = data
  } catch (e) {
    tasks.value = []
  }
})
</script>

<style scoped>
.compare-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.task-list { margin-bottom: 24px; }
.task-list h3 { font-size: 14px; color: #606266; }
.task-item { padding: 4px 0; }
.task-item label { cursor: pointer; font-size: 13px; display: flex; align-items: center; gap: 8px; }
.empty { color: #909399; font-size: 13px; }
.compare-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
.compare-table th, .compare-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; font-size: 13px; }
</style>
