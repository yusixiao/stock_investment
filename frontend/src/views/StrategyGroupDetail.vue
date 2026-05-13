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
import { freqLabel, statusClass, statusText, formatSummary } from '../utils/format'

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

function joinModeLabel(modes, i) {
  if (!modes || i >= modes.length) return ''
  return modes[i] === 'correlated' ? '[关联]' : '[独立]'
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
@import '../styles/common.css';
.group-detail-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.page-header h1 { flex: 1; margin: 0; }
.btn-back { background: none; border: none; color: #409eff; cursor: pointer; font-size: 14px; }
.header-actions { display: flex; gap: 8px; }
.btn-danger { padding: 6px 14px; background: #f56c6c; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.pipeline-display { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-bottom: 24px; padding: 12px; background: #f5f7fa; border-radius: 6px; }
.flow-step { display: flex; align-items: center; gap: 4px; }
.step-name { font-size: 13px; color: #606266; }
.flow-arrow { color: #909399; margin: 0 4px; font-size: 12px; }
.run-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.run-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.run-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.empty { color: #c0c4cc; font-size: 14px; }
</style>
