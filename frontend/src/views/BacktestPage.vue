<template>
  <div class="backtest-page">
    <h1>回测</h1>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" mode="backtest" />
    <ParamEditor :pipeline="pipeline" @update:overrides="overrides = $event" />
    <div class="date-range">
      <label>开始日期: <input v-model="startDate" type="date" /></label>
      <label>结束日期: <input v-model="endDate" type="date" /></label>
    </div>
    <button class="run-btn" @click="runBacktestPipeline" :disabled="!pipeline.length || running">
      {{ running ? '回测运行中...' : '运行回测' }}
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
      <button v-if="status === 'success'" class="view-btn" @click="$router.push('/backtest/result/' + taskId)">查看结果</button>
      <p v-if="status === 'failed'" class="error">回测失败</p>
    </div>
    <div class="task-history">
      <h3>历史任务</h3>
      <table v-if="tasks.length" class="task-table">
        <thead>
          <tr><th>任务ID</th><th>类型</th><th>状态</th><th>摘要</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id">
            <td>{{ t.task_id }}</td>
            <td><span :class="'type-badge type-' + t.task_type">{{ t.task_type === 'screener' ? '选股' : '回测' }}</span></td>
            <td><span :class="'task-status ' + t.status">{{ taskStatusText(t.status) }}</span></td>
            <td class="summary-cell">{{ formatSummary(t) }}</td>
            <td>{{ t.created_at }}</td>
            <td>
              <button v-if="t.status === 'success'" class="view-btn" @click="$router.push('/backtest/result/' + t.task_id)">查看结果</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无历史任务</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchStrategies, runBacktest, fetchBacktestStatus, fetchBacktestTasks } from '../api'
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
const tasks = ref([])
const progress = ref(null)
const progressPct = computed(() => {
  if (!progress.value || !progress.value.total) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})
let pollTimer = null

const taskStatusMap = { running: '运行中', success: '成功', failed: '失败' }
function taskStatusText(s) { return taskStatusMap[s] || s }

function formatSummary(t) {
  if (!t.summary) return '-'
  const s = t.summary
  if (s.screened_count !== undefined) return `选出 ${s.screened_count} 只`
  if (s.total_return !== undefined) {
    const ret = (s.total_return * 100).toFixed(2)
    const dd = s.max_drawdown !== null ? (s.max_drawdown * 100).toFixed(2) : '-'
    return `收益 ${ret}% / 回撤 ${dd}%`
  }
  return '-'
}

async function loadTasks() {
  try {
    const { data } = await fetchBacktestTasks()
    tasks.value = data
  } catch {}
}

async function runBacktestPipeline() {
  running.value = true
  progress.value = null
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
.backtest-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.date-range { margin-top: 16px; display: flex; gap: 16px; }
.date-range label { font-size: 14px; }
.date-range input { padding: 4px 8px; margin-left: 4px; }
.run-btn { margin-top: 16px; padding: 10px 24px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.run-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
.status { margin-top: 16px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.view-btn { margin-top: 8px; padding: 6px 16px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; }
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
.type-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; color: white; }
.type-screener { background: #67c23a; }
.type-backtest { background: #409eff; }
.summary-cell { font-size: 12px; color: #606266; }
.empty { color: #c0c4cc; font-size: 13px; }
</style>
