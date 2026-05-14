<template>
  <div class="update-card">
    <div class="card-header">
      <span class="card-label">数据状态</span>
    </div>
    <div class="status-grid">
      <div class="status-item" v-for="item in statusItems" :key="item.label">
        <div class="item-top">
          <span class="item-label">{{ item.label }}</span>
          <span :class="['item-status', 'status-' + item.status]">{{ item.statusText }}</span>
        </div>
        <div class="item-actions">
          <button v-for="btn in item.buttons" :key="btn.text" class="action-btn" :disabled="item.status === 'running'" @click="btn.action">{{ btn.text }}</button>
        </div>
        <div v-if="item.detail" class="item-detail">{{ item.detail }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchUpdateStatus, triggerUpdate as apiTriggerUpdate, triggerValuationUpdate, fetchValuationStatus, triggerDividendUpdate, fetchDividendStatus, triggerFinancialUpdate, fetchFinancialStatus } from '../api'

const status = ref('idle')
const result = ref(null)
let timer = null

const valStatus = ref('idle')
const valProgress = ref(null)
const valResult = ref(null)
let valTimer = null

const divStatus = ref('idle')
const divProgress = ref(null)
const divResult = ref(null)
let divTimer = null

const finStatus = ref('idle')
const finProgress = ref(null)
const finResult = ref(null)
let finTimer = null

const textMap = { idle: '就绪', running: '运行中', success: '完成', failed: '失败' }

const statusItems = computed(() => [
  {
    label: 'K线',
    status: status.value,
    statusText: textMap[status.value] || status.value,
    buttons: [{ text: '更新', action: doUpdate }],
    detail: result.value ? `成功:${result.value.updated} 跳过:${result.value.skipped} 失败:${result.value.failed}` : null,
  },
  {
    label: '估值',
    status: valStatus.value,
    statusText: textMap[valStatus.value] || valStatus.value,
    buttons: [{ text: '全量', action: () => triggerValUpdate('full') }, { text: '增量', action: () => triggerValUpdate('incremental') }],
    detail: valProgress.value && valStatus.value === 'running'
      ? `${valProgress.value.phase}: ${valProgress.value.current}/${valProgress.value.total}`
      : valResult.value && valStatus.value !== 'running'
        ? `成功:${valResult.value.success} 跳过:${valResult.value.skipped} 失败:${valResult.value.failed}`
        : null,
  },
  {
    label: '分红',
    status: divStatus.value,
    statusText: textMap[divStatus.value] || divStatus.value,
    buttons: [{ text: '全量', action: () => triggerDivUpdate('full') }, { text: '增量', action: () => triggerDivUpdate('incremental') }],
    detail: divProgress.value && divStatus.value === 'running'
      ? `${divProgress.value.phase}: ${divProgress.value.current}/${divProgress.value.total}`
      : divResult.value && divStatus.value !== 'running'
        ? `成功:${divResult.value.success} 跳过:${divResult.value.skipped} 失败:${divResult.value.failed}`
        : null,
  },
  {
    label: '财务',
    status: finStatus.value,
    statusText: textMap[finStatus.value] || finStatus.value,
    buttons: [{ text: '全量', action: () => triggerFinUpdate('full') }, { text: '增量', action: () => triggerFinUpdate('incremental') }],
    detail: finProgress.value && finStatus.value === 'running'
      ? `${finProgress.value.phase}: ${finProgress.value.current}/${finProgress.value.total}`
      : finResult.value && finStatus.value !== 'running'
        ? `成功:${finResult.value.success} 失败:${finResult.value.failed} 保存:${finResult.value.total_saved}`
        : null,
  },
])

async function pollStatus() {
  try {
    const { data } = await fetchUpdateStatus()
    status.value = data.status
    result.value = data.result
  } catch {}
}

async function doUpdate() {
  await apiTriggerUpdate()
  status.value = 'running'
  if (!timer) { timer = setInterval(pollStatus, 2000) }
}

async function pollValStatus() {
  try {
    const { data } = await fetchValuationStatus()
    valStatus.value = data.status
    valProgress.value = data.progress
    if (data.status !== 'running') {
      valResult.value = data.result
      if (valTimer) { clearInterval(valTimer); valTimer = null }
    }
  } catch {}
}

async function triggerValUpdate(mode) {
  await triggerValuationUpdate(mode)
  valStatus.value = 'running'
  valProgress.value = null
  valResult.value = null
  if (!valTimer) { valTimer = setInterval(pollValStatus, 2000) }
}

async function pollDivStatus() {
  try {
    const { data } = await fetchDividendStatus()
    divStatus.value = data.status
    divProgress.value = data.progress
    if (data.status !== 'running') {
      divResult.value = data.result
      if (divTimer) { clearInterval(divTimer); divTimer = null }
    }
  } catch {}
}

async function triggerDivUpdate(mode) {
  await triggerDividendUpdate(mode)
  divStatus.value = 'running'
  divProgress.value = null
  divResult.value = null
  if (!divTimer) { divTimer = setInterval(pollDivStatus, 2000) }
}

async function pollFinStatus() {
  try {
    const { data } = await fetchFinancialStatus()
    finStatus.value = data.status
    finProgress.value = data.progress
    if (data.status !== 'running') {
      finResult.value = data.result
      if (finTimer) { clearInterval(finTimer); finTimer = null }
    }
  } catch {}
}

async function triggerFinUpdate(mode) {
  await triggerFinancialUpdate(mode)
  finStatus.value = 'running'
  finProgress.value = null
  finResult.value = null
  if (!finTimer) { finTimer = setInterval(pollFinStatus, 2000) }
}

onMounted(() => { pollStatus(); pollValStatus(); pollDivStatus(); pollFinStatus() })
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (valTimer) clearInterval(valTimer)
  if (divTimer) clearInterval(divTimer)
  if (finTimer) clearInterval(finTimer)
})
</script>

<style scoped>
.update-card {
  background: var(--st-bg-card);
  border: 1px solid var(--st-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin-bottom: 12px;
}

.card-header {
  padding: 10px 16px;
  border-bottom: 1px solid var(--st-border);
  background: var(--st-bg-elevated);
}

.card-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--st-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
}

.status-item {
  padding: 12px 14px;
  border-right: 1px solid var(--st-border-light);
}

.status-item:last-child {
  border-right: none;
}

.item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.item-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--st-text-secondary);
}

.item-status {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

.status-idle { color: var(--st-text-muted); background: transparent; }
.status-running { background: hsl(37, 92%, 50%, 0.15); color: var(--st-warning); }
.status-success { background: hsl(152, 69%, 40%, 0.15); color: var(--st-success); }
.status-failed { background: hsl(349, 100%, 63%, 0.15); color: var(--st-danger); }

.item-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.action-btn {
  padding: 4px 10px;
  background: var(--st-bg-base);
  border: 1px solid var(--st-border);
  border-radius: var(--radius-sm);
  color: var(--st-text-secondary);
  font-family: var(--font-body);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.action-btn:hover:not(:disabled) {
  border-color: var(--st-accent);
  color: var(--st-accent);
  background: var(--st-accent-dim);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.item-detail {
  font-size: 11px;
  color: var(--st-text-muted);
  font-family: var(--font-mono);
}
</style>
