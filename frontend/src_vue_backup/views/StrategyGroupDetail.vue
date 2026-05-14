<template>
  <div class="page-container">
    <div class="page-header">
      <div class="header-left">
        <button class="btn-back" @click="$router.push('/backtest')">← BACK</button>
        <span class="page-title">{{ group?.name }}</span>
      </div>
      <div class="header-actions">
        <button class="btn-primary" @click="openRunDialog">RUN</button>
        <button class="btn-secondary" @click="$router.push(`/backtest/group/${groupId}/edit`)">EDIT</button>
        <button class="btn-danger" @click="doDelete">DELETE</button>
      </div>
    </div>

    <div v-if="group" class="panel">
      <div class="panel-header">
        <span class="panel-title">Pipeline</span>
      </div>
      <div class="panel-body pipeline-display">
        <span v-for="(step, i) in group.pipeline" :key="i" class="flow-step">
          <span :class="'freq-tag freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
          <span class="step-name">{{ step.name || step.class_name }}</span>
          <span v-if="i < group.pipeline.length - 1" class="flow-arrow">
            {{ joinModeLabel(group.join_modes, i) }} →
          </span>
        </span>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">Run History ({{ runs.length }})</span>
      </div>
      <div class="panel-body" style="padding:0">
        <table v-if="runs.length" class="data-table">
          <thead>
            <tr><th>#</th><th>TIME</th><th>RANGE</th><th>MODE</th><th>STATUS</th><th>SUMMARY</th><th>ACTION</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in runs" :key="r.run_id">
              <td>{{ runs.length - i }}</td>
              <td>{{ r.created_at }}</td>
              <td>{{ r.start_date || '-' }} ~ {{ r.end_date || '-' }}</td>
              <td>{{ r.execution_mode === 'auto' ? '一键' : '逐步' }}</td>
              <td><span :class="'badge badge-' + statusClass(r.status)">{{ statusText(r.status) }}</span></td>
              <td>{{ formatSummary(r.summary) }}</td>
              <td><button class="btn-view" @click="$router.push(`/backtest/group/${groupId}/run/${r.run_id}`)">VIEW</button></td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty-state"><span class="empty-text">NO RUNS YET</span></div>
      </div>
    </div>

    <div v-if="showRunDialog" class="dialog-overlay" @click.self="showRunDialog = false">
      <div class="run-dialog">
        <div class="dialog-header">
          <span class="panel-title">RUN GROUP</span>
          <button class="dialog-close" @click="showRunDialog = false">×</button>
        </div>
        <div class="dialog-body">
          <div v-if="hasBuySell && successRuns.length" class="form-row">
            <label class="form-label">SOURCE</label>
            <select v-model="sourceRunId" class="form-input">
              <option value="">重新选股</option>
              <option v-for="r in successRuns" :key="r.run_id" :value="r.run_id">
                {{ r.created_at?.slice(0, 16) }} | {{ formatSummary(r.summary) }}
              </option>
            </select>
          </div>
          <div class="form-row">
            <label class="form-label">START</label>
            <input v-model="runStartDate" type="date" class="form-input" min="2010-01-04" />
          </div>
          <div class="form-row">
            <label class="form-label">END</label>
            <input v-model="runEndDate" type="date" class="form-input" min="2010-01-04" />
          </div>
          <div class="form-row">
            <label class="form-label">CAPITAL</label>
            <div class="input-suffix">
              <input v-model.number="runCapital" type="number" class="form-input" min="1" step="1" />
              <span class="suffix">万</span>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label">MODE</label>
            <select v-model="runMode" class="form-input">
              <option value="auto">AUTO (一键执行)</option>
              <option value="stepwise">STEPWISE (逐步执行)</option>
            </select>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-primary" @click="doRun">EXECUTE</button>
          <button class="btn-secondary" @click="showRunDialog = false">CANCEL</button>
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
.header-left { display: flex; align-items: center; gap: 12px; }
.btn-back {
  background: none;
  border: none;
  color: var(--st-accent);
  cursor: pointer;
  font-family: var(--font-body);
  font-size: 11px;
}
.btn-back:hover { color: var(--st-accent-hover); }
.header-actions { display: flex; gap: 8px; }
.btn-danger {
  padding: 4px 12px;
  background: var(--st-danger);
  border: none;
  color: #ffffff;
  font-family: var(--font-body);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  text-transform: uppercase;
}
.btn-danger:hover { opacity: 0.85; }
.pipeline-display { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.flow-step { display: flex; align-items: center; gap: 3px; }
.step-name { font-size: 12px; color: var(--st-text-secondary); }
.flow-arrow { color: var(--st-text-muted); margin: 0 4px; font-size: 11px; }
.freq-tag {
  display: inline-block;
  padding: 0 4px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.freq-daily { background: #1a3a1a; color: #4caf50; }
.freq-weekly { background: #1a2a3a; color: #42a5f5; }
.freq-monthly { background: #3a2a1a; color: #ff8c00; }
.btn-view {
  padding: 2px 8px;
  background: transparent;
  border: 1px solid var(--st-border);
  color: var(--st-accent);
  font-family: var(--font-body);
  font-size: 10px;
  cursor: pointer;
  text-transform: uppercase;
}
.btn-view:hover { border-color: var(--st-accent); }
.empty-state { padding: 24px; text-align: center; }
.empty-text { font-size: 11px; color: var(--st-text-muted); text-transform: uppercase; }

.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.run-dialog {
  background: var(--st-bg-surface);
  border: 1px solid var(--st-border);
  width: 420px;
}
.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--st-border);
  background: var(--st-bg-panel-header);
}
.dialog-close {
  background: none;
  border: none;
  color: var(--st-text-muted);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}
.dialog-close:hover { color: var(--st-text-primary); }
.dialog-body { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.form-row { display: flex; align-items: center; gap: 8px; }
.form-label {
  width: 60px;
  font-size: 10px;
  font-weight: 700;
  color: var(--st-accent);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  flex-shrink: 0;
}
.form-input {
  flex: 1;
  padding: 4px 8px;
  background: var(--st-bg-base);
  border: 1px solid var(--st-border);
  color: var(--st-text-primary);
  font-family: var(--font-body);
  font-size: 12px;
}
.form-input:focus { outline: none; border-color: var(--st-accent); }
.input-suffix { display: flex; align-items: center; gap: 4px; flex: 1; }
.input-suffix .form-input { flex: 1; }
.suffix { font-size: 11px; color: var(--st-text-muted); }
.dialog-footer {
  padding: 8px 12px;
  border-top: 1px solid var(--st-border);
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
