<template>
  <div class="backtest-page">
    <h1>回测</h1>
    <div v-if="sourceInfo" class="source-card">
      <div class="source-card-content">
        <span>基于任务 <b>{{ sourceTaskId }}</b> 的选股结果（{{ sourceInfo.count }} 只股票）</span>
        <span v-if="sourceInfo.start_date || sourceInfo.end_date" class="source-dates">
          ，日期范围 {{ sourceInfo.start_date || '最早' }} ~ {{ sourceInfo.end_date || '最新' }}
        </span>
      </div>
      <button class="btn-clear-source" @click="clearSource">清除来源</button>
    </div>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" v-model:joinModes="joinModes" mode="backtest" />
    <ParamEditor :pipeline="pipeline" @update:overrides="overrides = $event" />
    <div class="date-range">
      <label>开始日期: <input v-model="startDate" type="date" :disabled="!!sourceInfo" /></label>
      <label>结束日期: <input v-model="endDate" type="date" :disabled="!!sourceInfo" /></label>
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
      <div class="task-list-header">
        <h3>历史任务</h3>
        <label class="show-deleted-label">
          <input type="checkbox" v-model="showDeleted" />
          显示已删除的任务
        </label>
      </div>
      <table v-if="tasks.length" class="task-table">
        <thead>
          <tr><th>任务ID</th><th>类型</th><th>状态</th><th>摘要</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id" :class="{ 'row-deleted': t.deleted }">
            <td>{{ t.task_id }}</td>
            <td><span :class="'type-badge type-' + t.task_type">{{ t.task_type === 'screener' ? '选股' : '回测' }}</span></td>
            <td><span :class="'task-status ' + t.status">{{ taskStatusText(t.status) }}</span></td>
            <td class="summary-cell">{{ formatSummary(t) }}</td>
            <td>{{ t.created_at }}</td>
            <td>
              <button v-if="t.status === 'success'" class="view-btn" @click="$router.push('/backtest/result/' + t.task_id)">查看结果</button>
              <button class="btn-delete" @click="onDeleteTask(t.task_id)" :disabled="t.deleted">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无历史任务</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchStrategies, runBacktest, fetchBacktestStatus, fetchBacktestTasks, fetchBacktestResult, deleteBacktestTask } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'
import ParamEditor from '../components/ParamEditor.vue'

const route = useRoute()

const strategies = ref([])
const pipeline = ref([])
const joinModes = ref([])
const overrides = ref({})
const startDate = ref('')
const endDate = ref('')
const taskId = ref('')
const status = ref('')
const running = ref(false)
const tasks = ref([])
const showDeleted = ref(false)
const progress = ref(null)
const sourceTaskId = ref(null)
const sourceInfo = ref(null)
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
    const { data } = await fetchBacktestTasks(showDeleted.value)
    tasks.value = data
  } catch {}
}

async function onDeleteTask(taskId) {
  await deleteBacktestTask(taskId)
  await loadTasks()
}

watch(showDeleted, () => loadTasks())

async function runBacktestPipeline() {
  running.value = true
  progress.value = null
  const body = {
    pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
    param_overrides: overrides.value,
  }
  if (joinModes.value.length > 0) {
    body.join_modes = joinModes.value
  }
  if (sourceTaskId.value) {
    body.source_task_id = sourceTaskId.value
  } else {
    if (startDate.value) body.start_date = startDate.value
    if (endDate.value) body.end_date = endDate.value
  }
  const { data } = await runBacktest(body)
  taskId.value = data.task_id
  status.value = 'running'
  pollTimer = setInterval(pollStatus, 2000)
}

function clearSource() {
  sourceTaskId.value = null
  sourceInfo.value = null
  startDate.value = ''
  endDate.value = ''
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
  const srcId = route.query.source_task_id
  if (srcId) {
    try {
      const { data: srcData } = await fetchBacktestResult(srcId)
      if (srcData.status === 'success' && srcData.result && srcData.result.screened_symbols) {
        sourceTaskId.value = srcId
        const syms = srcData.result.screened_symbols
        const count = Array.isArray(syms) ? syms.length : 0
        sourceInfo.value = {
          count,
          start_date: srcData.start_date,
          end_date: srcData.end_date,
        }
        if (srcData.start_date) startDate.value = srcData.start_date
        if (srcData.end_date) endDate.value = srcData.end_date
      }
    } catch {}
  }
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
.source-card { display: flex; align-items: center; justify-content: space-between; background: #ecf5ff; border: 1px solid #b3d8ff; border-radius: 6px; padding: 12px 16px; margin-bottom: 16px; }
.source-card-content { font-size: 14px; color: #303133; }
.source-dates { color: #606266; }
.btn-clear-source { background: transparent; border: 1px solid #dcdfe6; color: #606266; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-clear-source:hover { border-color: #409eff; color: #409eff; }
.task-list-header { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.task-list-header h3 { margin: 0; font-size: 16px; color: #303133; }
.show-deleted-label { font-size: 13px; color: #606266; display: flex; align-items: center; gap: 6px; cursor: pointer; }
.btn-delete { background: #f56c6c; color: white; border: none; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 12px; margin-left: 6px; }
.btn-delete:disabled { background: #dcdfe6; color: #909399; cursor: not-allowed; }
.row-deleted td { color: #c0c4cc; text-decoration: line-through; }
</style>
