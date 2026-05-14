<template>
  <div class="page-container">
    <div class="page-header">
      <div class="header-left">
        <button class="btn-back" @click="$router.push(`/backtest/group/${groupId}`)">← BACK</button>
        <span class="page-title">RUN DETAIL</span>
        <span v-if="run" class="run-meta">{{ run.start_date || '-' }} ~ {{ run.end_date || '-' }} | {{ run.execution_mode === 'auto' ? '一键' : '逐步' }}</span>
      </div>
    </div>

    <div v-if="run" class="run-content">
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">Steps</span>
          <span v-if="run.status === 'running'" class="badge badge-warning">RUNNING</span>
        </div>
        <div class="panel-body steps-flow">
          <div v-for="(step, i) in run.steps_result" :key="i" class="step-card" :class="{ active: expandedStep === i }" @click="expandedStep = expandedStep === i ? -1 : i">
            <div class="step-header">
              <span class="step-num">{{ stepName(i) }}</span>
              <span class="step-io">{{ step.input_count || 'ALL' }} → {{ step.output_count }}</span>
            </div>
            <div v-if="expandedStep === i && step.symbols" class="step-symbols">
              <span v-for="sym in step.symbols" :key="sym" class="symbol-tag" @click.stop="$router.push('/stock/' + sym)">{{ sym }}</span>
            </div>
          </div>
          <div v-if="isStepwise && !isComplete" class="next-step-section">
            <button class="btn-primary" @click="doNextStep" :disabled="stepping">
              {{ stepping ? 'RUNNING...' : 'NEXT STEP' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="run.error" class="error-banner">ERROR: {{ run.error }}</div>

      <div v-if="run.final_result && run.final_result.screened_symbols" class="panel">
        <div class="panel-header">
          <span class="panel-title">Screened Results ({{ activeSymbols.length }}<span v-if="excludedSymbols.length"> / -{{ excludedSymbols.length }}</span>)</span>
        </div>
        <div class="panel-body" style="padding:0">
          <table class="data-table">
            <thead>
              <tr><th>SYMBOL</th><th>MATCHES</th><th>DATES</th><th>ACTION</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in activeSymbols" :key="item.symbol">
                <td><a class="link" @click="$router.push('/stock/' + item.symbol)">{{ item.symbol }}</a></td>
                <td class="col-number">{{ item.match_count }}</td>
                <td>{{ item.dates }}</td>
                <td><button class="btn-exclude" @click="openExcludeDialog(item.symbol)">EXCLUDE</button></td>
              </tr>
              <tr v-if="excludedSymbols.length" class="divider-row"><td colspan="4"><span class="divider-text">EXCLUDED</span></td></tr>
              <tr v-for="item in excludedSymbols" :key="item.symbol" class="excluded-row">
                <td><a class="link" @click="$router.push('/stock/' + item.symbol)">{{ item.symbol }}</a></td>
                <td class="col-number">{{ item.match_count }}</td>
                <td class="reason-cell">{{ exclusionMap[item.symbol] }}</td>
                <td><button class="btn-restore" @click="doRestore(item.symbol)">RESTORE</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="run.final_result && run.final_result.metrics" class="panel">
        <div class="panel-header">
          <span class="panel-title">Backtest Result</span>
        </div>
        <div class="panel-body">
          <button class="btn-primary" @click="$router.push('/backtest/result/' + lastTaskId)">VIEW FULL RESULT</button>
        </div>
      </div>
    </div>
    <div v-else class="loading-text">LOADING...</div>

    <div v-if="showExcludeDialog" class="dialog-overlay" @click.self="showExcludeDialog = false">
      <div class="run-dialog">
        <div class="dialog-header">
          <span class="panel-title">EXCLUDE: {{ excludeTarget }}</span>
          <button class="dialog-close" @click="showExcludeDialog = false">×</button>
        </div>
        <div class="dialog-body">
          <div class="form-row">
            <label class="form-label">REASON</label>
            <input v-model="excludeReason" type="text" class="form-input" placeholder="如: 地方银行" />
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-primary" @click="doExclude">CONFIRM</button>
          <button class="btn-secondary" @click="showExcludeDialog = false">CANCEL</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchRun, fetchRunStatus, nextStep, fetchGroup, fetchExclusions, addExclusion, removeExclusion } from '../api'

const route = useRoute()
const groupId = route.params.groupId
const runId = route.params.runId

const run = ref(null)
const group = ref(null)
const exclusions = ref([])
const expandedStep = ref(-1)
const stepping = ref(false)
const showExcludeDialog = ref(false)
const excludeTarget = ref('')
const excludeReason = ref('')
let pollTimer = null

function stepName(index) {
  const stepResult = run.value?.steps_result?.[index]
  if (stepResult?.name) return stepResult.name
  if (group.value?.pipeline?.[index]) {
    const step = group.value.pipeline[index]
    return step.name || step.class_name
  }
  return `Step ${index + 1}`
}

const isStepwise = computed(() => run.value?.execution_mode === 'stepwise')
const isComplete = computed(() => run.value?.status === 'success' || run.value?.status === 'failed')

const exclusionMap = computed(() => {
  const map = {}
  for (const e of exclusions.value) {
    map[e.symbol] = e.reason || ''
  }
  return map
})

const excludedSet = computed(() => new Set(Object.keys(exclusionMap.value)))

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

const activeSymbols = computed(() => finalSymbols.value.filter(s => !excludedSet.value.has(s.symbol)))
const excludedSymbols = computed(() => finalSymbols.value.filter(s => excludedSet.value.has(s.symbol)))

const lastTaskId = computed(() => {
  if (!run.value?.steps_result?.length) return ''
  return run.value.steps_result[run.value.steps_result.length - 1].task_id
})

async function loadRun() {
  const { data } = await fetchRun(runId)
  run.value = data
}

async function loadExclusions() {
  const { data } = await fetchExclusions(runId)
  exclusions.value = data
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

function openExcludeDialog(symbol) {
  excludeTarget.value = symbol
  excludeReason.value = ''
  showExcludeDialog.value = true
}

async function doExclude() {
  await addExclusion(runId, excludeTarget.value, excludeReason.value)
  showExcludeDialog.value = false
  await loadExclusions()
}

async function doRestore(symbol) {
  await removeExclusion(runId, symbol)
  await loadExclusions()
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
  const { data } = await fetchGroup(groupId)
  group.value = data
  await loadExclusions()
  if (!isComplete.value) {
    pollTimer = setInterval(pollRunStatus, 3000)
  }
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
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
.run-meta { font-size: 11px; color: var(--st-text-muted); }
.steps-flow { display: flex; flex-wrap: wrap; gap: 8px; }
.step-card {
  border: 1px solid var(--st-border);
  padding: 8px 12px;
  cursor: pointer;
  min-width: 100px;
  transition: border-color 0.1s;
}
.step-card:hover { border-color: var(--st-accent); }
.step-card.active { border-color: var(--st-accent); background: var(--st-accent-dim); }
.step-header { display: flex; flex-direction: column; gap: 2px; }
.step-num { font-size: 12px; font-weight: 700; color: var(--st-text-primary); }
.step-io { font-size: 10px; color: var(--st-text-muted); }
.step-symbols { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 3px; max-height: 80px; overflow-y: auto; }
.symbol-tag {
  padding: 1px 6px;
  background: var(--st-bg-elevated);
  border: 1px solid var(--st-border);
  font-size: 11px;
  color: var(--st-text-secondary);
  cursor: pointer;
}
.symbol-tag:hover { border-color: var(--st-accent); color: var(--st-accent); }
.next-step-section { display: flex; align-items: center; }
.error-banner {
  padding: 6px 10px;
  background: rgba(255, 23, 68, 0.1);
  border: 1px solid var(--st-danger);
  color: var(--st-danger);
  font-size: 11px;
  margin-bottom: 8px;
}
.link { color: var(--st-accent); cursor: pointer; }
.link:hover { color: var(--st-accent-hover); }
.btn-exclude {
  padding: 2px 8px;
  background: transparent;
  border: 1px solid var(--st-border);
  color: var(--st-text-muted);
  font-family: var(--font-body);
  font-size: 10px;
  cursor: pointer;
  text-transform: uppercase;
}
.btn-exclude:hover { border-color: var(--st-danger); color: var(--st-danger); }
.btn-restore {
  padding: 2px 8px;
  background: transparent;
  border: 1px solid var(--st-border);
  color: var(--st-text-muted);
  font-family: var(--font-body);
  font-size: 10px;
  cursor: pointer;
  text-transform: uppercase;
}
.btn-restore:hover { border-color: var(--st-success); color: var(--st-success); }
.divider-row td { padding: 8px; text-align: center; border-bottom: none; }
.divider-text { color: var(--st-text-muted); font-size: 10px; letter-spacing: 0.05em; }
.excluded-row { opacity: 0.4; }
.reason-cell { font-style: italic; color: var(--st-text-muted); }
.loading-text { color: var(--st-text-muted); font-size: 11px; text-transform: uppercase; }

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
  width: 380px;
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
.dialog-footer {
  padding: 8px 12px;
  border-top: 1px solid var(--st-border);
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
