<template>
  <div class="run-detail-page">
    <div class="page-header">
      <button class="btn-back" @click="$router.push(`/backtest/group/${groupId}`)">← 返回</button>
      <h1>运行详情</h1>
      <span v-if="run" class="run-meta">{{ run.start_date || '-' }} ~ {{ run.end_date || '-' }} | {{ run.execution_mode === 'auto' ? '一键执行' : '逐步执行' }}</span>
    </div>
    <div v-if="run" class="run-content">
      <div class="steps-flow">
        <div v-for="(step, i) in run.steps_result" :key="i" class="step-card" :class="{ active: expandedStep === i }" @click="expandedStep = expandedStep === i ? -1 : i">
          <div class="step-header">
            <span class="step-num">步骤 {{ step.step }}</span>
            <span class="step-io">{{ step.input_count || '全量' }} → {{ step.output_count }}</span>
          </div>
          <div v-if="expandedStep === i && step.symbols" class="step-symbols">
            <span v-for="sym in step.symbols" :key="sym" class="symbol-tag" @click.stop="$router.push('/stock/' + sym)">{{ sym }}</span>
          </div>
        </div>
        <div v-if="isStepwise && !isComplete" class="next-step-section">
          <button class="btn-primary" @click="doNextStep" :disabled="stepping">
            {{ stepping ? '执行中...' : '执行下一步' }}
          </button>
        </div>
      </div>
      <div v-if="run.status === 'running'" class="running-msg">运行中...</div>
      <div v-if="run.error" class="error-msg">错误: {{ run.error }}</div>
      <div v-if="run.final_result && run.final_result.screened_symbols" class="final-result">
        <h2>最终结果 ({{ run.final_result.screened_symbols.length }} 只)</h2>
        <table class="result-table">
          <thead>
            <tr><th>代码</th><th>匹配次数</th><th>匹配日期</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in finalSymbols" :key="item.symbol">
              <td><a @click="$router.push('/stock/' + item.symbol)">{{ item.symbol }}</a></td>
              <td>{{ item.match_count }}</td>
              <td>{{ item.dates }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="run.final_result && run.final_result.metrics" class="final-result">
        <h2>回测结果</h2>
        <button class="view-btn" @click="$router.push('/backtest/result/' + lastTaskId)">查看详细回测结果</button>
      </div>
    </div>
    <div v-else class="loading">加载中...</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchRun, fetchRunStatus, nextStep } from '../api'

const route = useRoute()
const groupId = route.params.groupId
const runId = route.params.runId

const run = ref(null)
const expandedStep = ref(-1)
const stepping = ref(false)
let pollTimer = null

const isStepwise = computed(() => run.value?.execution_mode === 'stepwise')
const isComplete = computed(() => run.value?.status === 'success' || run.value?.status === 'failed')

const finalSymbols = computed(() => {
  if (!run.value?.final_result?.screened_symbols) return []
  const items = run.value.final_result.screened_symbols
  return items.map(item => {
    if (typeof item === 'string') return { symbol: item, match_count: 0, dates: '' }
    return {
      symbol: item.symbol,
      match_count: item.match_dates?.length || 0,
      dates: (item.match_dates || []).slice(0, 5).join(', ') + (item.match_dates?.length > 5 ? '...' : ''),
    }
  })
})

const lastTaskId = computed(() => {
  if (!run.value?.steps_result?.length) return ''
  return run.value.steps_result[run.value.steps_result.length - 1].task_id
})

async function loadRun() {
  const { data } = await fetchRun(runId)
  run.value = data
}

async function doNextStep() {
  stepping.value = true
  try {
    await nextStep(runId)
    await loadRun()
  } finally {
    stepping.value = false
  }
}

async function pollRunStatus() {
  if (!run.value || isComplete.value) return
  try {
    const { data } = await fetchRunStatus(runId)
    if (data.status !== run.value.status) {
      await loadRun()
    }
    if (data.status === 'success' || data.status === 'failed') {
      clearInterval(pollTimer)
    }
  } catch {}
}

onMounted(async () => {
  await loadRun()
  if (!isComplete.value) {
    pollTimer = setInterval(pollRunStatus, 3000)
  }
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.run-detail-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.page-header h1 { margin: 0; }
.run-meta { font-size: 13px; color: #909399; }
.btn-back { background: none; border: none; color: #409eff; cursor: pointer; font-size: 14px; }
.steps-flow { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.step-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px 16px; cursor: pointer; min-width: 120px; transition: all 0.2s; }
.step-card:hover { border-color: #409eff; }
.step-card.active { border-color: #409eff; background: #ecf5ff; }
.step-header { display: flex; flex-direction: column; gap: 4px; }
.step-num { font-size: 14px; font-weight: 600; color: #303133; }
.step-io { font-size: 12px; color: #909399; }
.step-symbols { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; max-height: 100px; overflow-y: auto; }
.symbol-tag { padding: 2px 8px; background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 3px; font-size: 12px; cursor: pointer; }
.symbol-tag:hover { background: #409eff; color: white; }
.next-step-section { display: flex; align-items: center; }
.btn-primary { padding: 8px 16px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-primary:disabled { background: #c0c4cc; cursor: not-allowed; }
.running-msg { color: #e6a23c; font-size: 14px; }
.error-msg { color: #f56c6c; font-size: 14px; padding: 8px 12px; background: #ffebee; border-radius: 4px; }
.final-result { margin-top: 24px; }
.final-result h2 { font-size: 16px; color: #303133; margin-bottom: 12px; }
.result-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.result-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.result-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.result-table a { color: #409eff; cursor: pointer; }
.view-btn { padding: 6px 14px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.loading { color: #909399; font-size: 14px; }
</style>
