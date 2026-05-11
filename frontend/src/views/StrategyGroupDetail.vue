<template>
  <div class="group-detail-page">
    <div class="page-header">
      <button class="btn-back" @click="$router.push('/backtest')">← 返回</button>
      <h1>{{ group?.name }}</h1>
      <div class="header-actions">
        <button class="btn-primary" @click="openRunDialog">运行</button>
        <button class="btn-secondary" @click="$router.push(`/backtest/group/${groupId}/edit`)">编辑</button>
        <button class="btn-danger" @click="doDelete">删除</button>
      </div>
    </div>
    <div v-if="group" class="pipeline-display">
      <span v-for="(step, i) in group.pipeline" :key="i" class="flow-step">
        <span :class="'freq-badge freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
        <span class="step-name">{{ step.name || step.class_name }}</span>
        <span v-if="i < group.pipeline.length - 1" class="flow-arrow">
          {{ joinModeLabel(group.join_modes, i) }} →
        </span>
      </span>
    </div>
    <h2>运行历史</h2>
    <table v-if="runs.length" class="run-table">
      <thead>
        <tr><th>#</th><th>运行时间</th><th>日期范围</th><th>模式</th><th>状态</th><th>结果摘要</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in runs" :key="r.run_id">
          <td>{{ runs.length - i }}</td>
          <td>{{ r.created_at }}</td>
          <td>{{ r.start_date || '-' }} ~ {{ r.end_date || '-' }}</td>
          <td>{{ r.execution_mode === 'auto' ? '一键' : '逐步' }}</td>
          <td><span :class="'status-badge status-' + statusClass(r.status)">{{ statusText(r.status) }}</span></td>
          <td>{{ formatSummary(r.summary) }}</td>
          <td><button class="view-btn" @click="$router.push(`/backtest/group/${groupId}/run/${r.run_id}`)">查看</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty">暂无运行记录</p>
    <div v-if="showRunDialog" class="dialog-overlay" @click.self="showRunDialog = false">
      <div class="dialog">
        <h3>运行策略组</h3>
        <div class="dialog-form">
          <label v-if="hasBuySell && successRuns.length">信号来源:
            <select v-model="sourceRunId">
              <option value="">不使用（重新选股）</option>
              <option v-for="r in successRuns" :key="r.run_id" :value="r.run_id">
                {{ r.created_at?.slice(0, 16) }} | {{ formatSummary(r.summary) }}
              </option>
            </select>
          </label>
          <label>开始日期: <input v-model="runStartDate" type="date" min="2010-01-04" /></label>
          <label>结束日期: <input v-model="runEndDate" type="date" min="2010-01-04" /></label>
          <label>起始资金(万): <input v-model.number="runCapital" type="number" min="1" step="1" /></label>
          <label>执行模式:
            <select v-model="runMode">
              <option value="auto">一键执行</option>
              <option value="stepwise">逐步执行</option>
            </select>
          </label>
        </div>
        <div class="dialog-actions">
          <button class="btn-primary" @click="doRun">开始</button>
          <button class="btn-secondary" @click="showRunDialog = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchGroup, fetchGroupRuns, runGroup, deleteGroup } from '../api'

const route = useRoute()
const router = useRouter()
const groupId = route.params.groupId

const group = ref(null)
const runs = ref([])
const showRunDialog = ref(false)
const runStartDate = ref('')
const runEndDate = ref('')
const runMode = ref('auto')
const runCapital = ref(100)
const sourceRunId = ref('')

const hasBuySell = computed(() => {
  if (!group.value?.pipeline) return false
  return group.value.pipeline.some(s =>
    s.strategy_type === 'buy' || s.strategy_type === 'sell' ||
    /buy|sell/i.test(s.class_name || '')
  )
})

const successRuns = computed(() => {
  return runs.value.filter(r => r.status === 'success' && r.summary?.screened_count > 0)
})

const freqMap = { daily: '日线', weekly: '周线', monthly: '月线' }
function freqLabel(f) { return freqMap[f] || '日线' }

function joinModeLabel(modes, i) {
  if (!modes || i >= modes.length) return ''
  return modes[i] === 'correlated' ? '[关联]' : '[独立]'
}

function statusClass(s) {
  if (s === 'success') return 'success'
  if (s === 'failed') return 'failed'
  if (s === 'running') return 'running'
  return 'pending'
}

function statusText(s) {
  if (s === 'success') return '成功'
  if (s === 'failed') return '失败'
  if (s === 'running') return '运行中'
  if (s.startsWith('step_') && s.endsWith('_done')) {
    const m = s.match(/\d+/)
    return m ? `第${m[0]}步完成` : s
  }
  return s
}

function formatSummary(s) {
  if (!s) return '-'
  if (s.screened_count !== undefined) return `选出 ${s.screened_count} 只`
  if (s.total_return !== undefined) return `收益 ${(s.total_return * 100).toFixed(2)}%`
  return '-'
}

function openRunDialog() {
  runStartDate.value = ''
  runEndDate.value = ''
  runMode.value = 'auto'
  sourceRunId.value = ''
  showRunDialog.value = true
}

async function doRun() {
  const { data } = await runGroup(groupId, {
    start_date: runStartDate.value || undefined,
    end_date: runEndDate.value || undefined,
    execution_mode: runMode.value,
    initial_capital: runCapital.value * 10000,
    source_run_id: sourceRunId.value || undefined,
  })
  showRunDialog.value = false
  router.push(`/backtest/group/${groupId}/run/${data.run_id}`)
}

async function doDelete() {
  if (!confirm('确认删除此策略组及所有运行记录？')) return
  await deleteGroup(groupId)
  router.push('/backtest')
}

onMounted(async () => {
  const { data: g } = await fetchGroup(groupId)
  group.value = g
  const { data: r } = await fetchGroupRuns(groupId)
  runs.value = r
})
</script>

<style scoped>
.group-detail-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.page-header h1 { flex: 1; margin: 0; }
.btn-back { background: none; border: none; color: #409eff; cursor: pointer; font-size: 14px; }
.header-actions { display: flex; gap: 8px; }
.btn-primary { padding: 6px 14px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-secondary { padding: 6px 14px; background: white; color: #606266; border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-danger { padding: 6px 14px; background: #f56c6c; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.pipeline-display { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-bottom: 24px; padding: 12px; background: #f5f7fa; border-radius: 6px; }
.flow-step { display: flex; align-items: center; gap: 4px; }
.freq-badge { padding: 2px 6px; border-radius: 3px; font-size: 11px; color: white; }
.freq-daily { background: #909399; }
.freq-weekly { background: #e6a23c; }
.freq-monthly { background: #f56c6c; }
.step-name { font-size: 13px; color: #606266; }
.flow-arrow { color: #909399; margin: 0 4px; font-size: 12px; }
.run-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.run-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.run-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.status-success { background: #e8f5e9; color: #2e7d32; }
.status-failed { background: #ffebee; color: #c62828; }
.status-running { background: #fff3e0; color: #e65100; }
.status-pending { background: #e3f2fd; color: #1565c0; }
.view-btn { padding: 4px 12px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.empty { color: #c0c4cc; font-size: 14px; }
.dialog-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.dialog { background: white; border-radius: 8px; padding: 24px; min-width: 400px; }
.dialog h3 { margin: 0 0 16px; font-size: 16px; }
.dialog-form { display: flex; flex-direction: column; gap: 12px; }
.dialog-form label { font-size: 14px; display: flex; align-items: center; gap: 8px; }
.dialog-form input, .dialog-form select { padding: 4px 8px; }
.dialog-actions { margin-top: 20px; display: flex; gap: 12px; justify-content: flex-end; }
</style>
