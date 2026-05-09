<template>
  <div class="debug-page">
    <h1>策略调试</h1>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" mode="screener" />
    <ParamEditor :pipeline="pipeline" @update:overrides="overrides = $event" />
    <div class="date-range">
      <label>开始日期: <input v-model="startDate" type="date" min="2010-01-04" /></label>
      <label>结束日期: <input v-model="endDate" type="date" min="2010-01-04" /></label>
    </div>
    <button class="run-btn" @click="runDebug" :disabled="!pipeline.length || running">
      {{ running ? '运行中...' : '运行调试' }}
    </button>
    <div v-if="taskId" class="status">
      <p>任务ID: {{ taskId }} | 状态: {{ status }}</p>
      <div v-if="progress && status === 'running'" class="progress-info">
        <p class="progress-phase">{{ progress.phase }}</p>
        <div v-if="progress.total > 0" class="progress-bar-wrap">
          <div class="progress-bar" :style="{ width: progressPct + '%' }"></div>
        </div>
        <p v-if="progress.total > 0" class="progress-text">{{ progress.current }} / {{ progress.total }} ({{ progressPct }}%)</p>
      </div>
      <div v-if="status === 'success' && result" class="result">
        <h2>选股结果 ({{ resultCount }} 只)</h2>
        <div class="symbol-grid">
          <span v-for="sym in resultSymbols" :key="sym" class="symbol-tag" @click="$router.push('/stock/' + sym)">{{ sym }}</span>
        </div>
      </div>
      <p v-if="status === 'failed'" class="error">运行失败</p>
    </div>
    <div class="task-history">
      <h3>调试历史</h3>
      <table v-if="tasks.length" class="task-table">
        <thead>
          <tr><th>任务ID</th><th>状态</th><th>摘要</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id">
            <td>{{ t.task_id }}</td>
            <td><span :class="'task-status ' + t.status">{{ statusText(t.status) }}</span></td>
            <td>{{ formatSummary(t) }}</td>
            <td>{{ t.created_at }}</td>
            <td>
              <button v-if="t.status === 'success'" class="view-btn" @click="$router.push('/backtest/result/' + t.task_id)">查看</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无调试记录</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchStrategies, runBacktest, fetchBacktestStatus, fetchBacktestResult, fetchBacktestTasks } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'
import ParamEditor from '../components/ParamEditor.vue'

const strategies = ref([])
const pipeline = ref([])
const overrides = ref({})
const startDate = ref('')
const endDate = ref('')
const taskId = ref('')
const status = ref('')
const running = ref(false)
const result = ref(null)
const progress = ref(null)
const tasks = ref([])
const progressPct = computed(() => {
  if (!progress.value || !progress.value.total) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})
let pollTimer = null

const resultSymbols = computed(() => {
  if (!result.value || !result.value.screened_symbols) return []
  return result.value.screened_symbols.map(s => typeof s === 'string' ? s : s.symbol)
})
const resultCount = computed(() => resultSymbols.value.length)

const statusMap = { running: '运行中', success: '成功', failed: '失败' }
function statusText(s) { return statusMap[s] || s }

function formatSummary(t) {
  if (!t.summary) return '-'
  if (t.summary.screened_count !== undefined) return `选出 ${t.summary.screened_count} 只`
  return '-'
}

async function loadTasks() {
  try {
    const { data } = await fetchBacktestTasks()
    tasks.value = data.filter(t => t.task_type === 'screener' || t.task_type === 'debug')
  } catch {}
}

async function runDebug() {
  running.value = true
  progress.value = null
  result.value = null
  const body = {
    pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
    param_overrides: overrides.value,
  }
  if (startDate.value) body.start_date = startDate.value
  if (endDate.value) body.end_date = endDate.value
  const { data } = await runBacktest(body)
  taskId.value = data.task_id
  status.value = 'running'
  pollTimer = setInterval(pollStatus, 2000)
}

async function pollStatus() {
  if (!taskId.value) return
  try {
    const { data } = await fetchBacktestStatus(taskId.value)
    status.value = data.status
    progress.value = data.progress || null
    if (data.status !== 'running') {
      running.value = false
      progress.value = null
      clearInterval(pollTimer)
      if (data.status === 'success') {
        const { data: r } = await fetchBacktestResult(taskId.value)
        result.value = r.result
      }
      loadTasks()
    }
  } catch {
    status.value = 'failed'
    running.value = false
    progress.value = null
    clearInterval(pollTimer)
  }
}

onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
  loadTasks()
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.debug-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.date-range { margin-top: 16px; display: flex; gap: 16px; align-items: center; }
.date-range label { font-size: 14px; }
.date-range input { padding: 4px 8px; margin-left: 4px; }
.run-btn { margin-top: 16px; padding: 10px 24px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.run-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
.status { margin-top: 16px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.result { margin-top: 12px; }
.symbol-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.symbol-tag { padding: 4px 10px; background: #ecf5ff; border: 1px solid #b3d8ff; border-radius: 4px; cursor: pointer; font-size: 13px; }
.symbol-tag:hover { background: #409eff; color: white; }
.view-btn { padding: 4px 12px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.error { color: #f56c6c; }
.progress-info { margin-top: 8px; }
.progress-phase { font-size: 13px; color: #606266; margin: 0 0 6px; }
.progress-bar-wrap { width: 100%; height: 16px; background: #e4e7ed; border-radius: 8px; overflow: hidden; }
.progress-bar { height: 100%; background: #409eff; border-radius: 8px; transition: width 0.3s ease; }
.progress-text { font-size: 12px; color: #909399; margin: 4px 0 0; }
.task-history { margin-top: 32px; }
.task-history h3 { font-size: 16px; color: #303133; margin-bottom: 12px; }
.task-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.task-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.task-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.task-status { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.task-status.success { background: #e8f5e9; color: #2e7d32; }
.task-status.failed { background: #ffebee; color: #c62828; }
.task-status.running { background: #fff3e0; color: #e65100; }
.empty { color: #c0c4cc; font-size: 13px; }
</style>
