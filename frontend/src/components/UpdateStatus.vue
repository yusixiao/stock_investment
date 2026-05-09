<template>
  <div class="update-status">
    <div class="status-row">
      <span class="status-label">行情数据:</span>
      <span :class="['status-badge', statusClass]">{{ statusText }}</span>
      <button :disabled="status === 'running'" @click="doUpdate">
        {{ status === 'running' ? '更新中...' : '增量更新' }}
      </button>
    </div>
    <div v-if="result" class="status-detail">
      <span>成功: {{ result.updated }}</span>
      <span>跳过: {{ result.skipped }}</span>
      <span>失败: {{ result.failed }}</span>
      <span>新增: {{ result.new_stocks }}</span>
      <span v-if="result.finished_at">完成于: {{ result.finished_at }}</span>
    </div>

    <div class="status-row" style="margin-top: 12px;">
      <span class="status-label">估值数据:</span>
      <span :class="['status-badge', valStatusClass]">{{ valStatusText }}</span>
      <button :disabled="valStatus === 'running'" @click="triggerValUpdate('full')">全量拉取</button>
      <button :disabled="valStatus === 'running'" @click="triggerValUpdate('incremental')">增量更新</button>
    </div>
    <div v-if="valProgress && valStatus === 'running'" class="status-detail">
      <span>{{ valProgress.phase }}: {{ valProgress.current }}/{{ valProgress.total }}</span>
      <span>({{ Math.round(valProgress.current / valProgress.total * 100) }}%)</span>
    </div>
    <div v-if="valResult && valStatus !== 'running'" class="status-detail">
      <span>成功: {{ valResult.success }}</span>
      <span>跳过: {{ valResult.skipped }}</span>
      <span>失败: {{ valResult.failed }}</span>
    </div>

    <div class="status-row" style="margin-top: 12px;">
      <span class="status-label">分红数据:</span>
      <span :class="['status-badge', divStatusClass]">{{ divStatusText }}</span>
      <button :disabled="divStatus === 'running'" @click="triggerDivUpdate('full')">全量拉取</button>
      <button :disabled="divStatus === 'running'" @click="triggerDivUpdate('incremental')">增量更新</button>
    </div>
    <div v-if="divProgress && divStatus === 'running'" class="status-detail">
      <span>{{ divProgress.phase }}: {{ divProgress.current }}/{{ divProgress.total }}</span>
      <span>({{ Math.round(divProgress.current / divProgress.total * 100) }}%)</span>
    </div>
    <div v-if="divResult && divStatus !== 'running'" class="status-detail">
      <span>成功: {{ divResult.success }}</span>
      <span>跳过: {{ divResult.skipped }}</span>
      <span>失败: {{ divResult.failed }}</span>
    </div>

    <div class="status-row" style="margin-top: 12px;">
      <span class="status-label">财报数据:</span>
      <span :class="['status-badge', finStatusClass]">{{ finStatusText }}</span>
      <button :disabled="finStatus === 'running'" @click="triggerFinUpdate('full')">全量拉取</button>
      <button :disabled="finStatus === 'running'" @click="triggerFinUpdate('incremental')">增量更新</button>
    </div>
    <div v-if="finProgress && finStatus === 'running'" class="status-detail">
      <span>{{ finProgress.phase }}: {{ finProgress.current }}/{{ finProgress.total }}</span>
      <span>({{ Math.round(finProgress.current / finProgress.total * 100) }}%)</span>
    </div>
    <div v-if="finResult && finStatus !== 'running'" class="status-detail">
      <span>成功: {{ finResult.success }}</span>
      <span>失败: {{ finResult.failed }}</span>
      <span>写入: {{ finResult.total_saved }}条</span>
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

const statusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[status.value] || status.value
})

const statusClass = computed(() => status.value)

const valStatusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[valStatus.value] || valStatus.value
})

const valStatusClass = computed(() => valStatus.value)

const divStatusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[divStatus.value] || divStatus.value
})

const divStatusClass = computed(() => divStatus.value)

const finStatusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[finStatus.value] || finStatus.value
})

const finStatusClass = computed(() => finStatus.value)

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
  if (!timer) {
    timer = setInterval(pollStatus, 2000)
  }
}

async function pollValStatus() {
  try {
    const { data } = await fetchValuationStatus()
    valStatus.value = data.status
    valProgress.value = data.progress
    if (data.status !== 'running') {
      valResult.value = data.result
      if (valTimer) {
        clearInterval(valTimer)
        valTimer = null
      }
    }
  } catch {}
}

async function triggerValUpdate(mode) {
  await triggerValuationUpdate(mode)
  valStatus.value = 'running'
  valProgress.value = null
  valResult.value = null
  if (!valTimer) {
    valTimer = setInterval(pollValStatus, 2000)
  }
}

async function pollDivStatus() {
  try {
    const { data } = await fetchDividendStatus()
    divStatus.value = data.status
    divProgress.value = data.progress
    if (data.status !== 'running') {
      divResult.value = data.result
      if (divTimer) {
        clearInterval(divTimer)
        divTimer = null
      }
    }
  } catch {}
}

async function triggerDivUpdate(mode) {
  await triggerDividendUpdate(mode)
  divStatus.value = 'running'
  divProgress.value = null
  divResult.value = null
  if (!divTimer) {
    divTimer = setInterval(pollDivStatus, 2000)
  }
}

async function pollFinStatus() {
  try {
    const { data } = await fetchFinancialStatus()
    finStatus.value = data.status
    finProgress.value = data.progress
    if (data.status !== 'running') {
      finResult.value = data.result
      if (finTimer) {
        clearInterval(finTimer)
        finTimer = null
      }
    }
  } catch {}
}

async function triggerFinUpdate(mode) {
  await triggerFinancialUpdate(mode)
  finStatus.value = 'running'
  finProgress.value = null
  finResult.value = null
  if (!finTimer) {
    finTimer = setInterval(pollFinStatus, 2000)
  }
}

onMounted(() => {
  pollStatus()
  pollValStatus()
  pollDivStatus()
  pollFinStatus()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (valTimer) clearInterval(valTimer)
  if (divTimer) clearInterval(divTimer)
  if (finTimer) clearInterval(finTimer)
})
</script>

<style scoped>
.update-status { padding: 12px; background: #f5f7fa; border-radius: 6px; margin-bottom: 16px; }
.status-row { display: flex; align-items: center; gap: 12px; }
.status-label { font-weight: bold; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 13px; }
.status-badge.idle { background: #e0e0e0; }
.status-badge.running { background: #fff3e0; color: #e65100; }
.status-badge.success { background: #e8f5e9; color: #2e7d32; }
.status-badge.failed { background: #ffebee; color: #c62828; }
.status-detail { margin-top: 8px; font-size: 13px; display: flex; gap: 16px; color: #666; }
button { padding: 6px 16px; cursor: pointer; border: 1px solid #dcdfe6; border-radius: 4px; background: white; }
button:disabled { cursor: not-allowed; opacity: 0.5; }
</style>
