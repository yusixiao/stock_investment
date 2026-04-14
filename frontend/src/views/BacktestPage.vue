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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchStrategies, runBacktest, fetchBacktestStatus } from '../api'
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
const progress = ref(null)
const progressPct = computed(() => {
  if (!progress.value || !progress.value.total) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})
let pollTimer = null

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
</style>
