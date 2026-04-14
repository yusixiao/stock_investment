<template>
  <div class="update-status">
    <div class="status-row">
      <span class="status-label">数据更新:</span>
      <span :class="['status-badge', statusClass]">{{ statusText }}</span>
      <label class="date-pick">日期: <input type="date" v-model="targetDate" :disabled="status === 'running'" /></label>
      <button :disabled="status === 'running'" @click="triggerUpdate">
        {{ status === 'running' ? '更新中...' : '立即更新' }}
      </button>
    </div>
    <div v-if="result" class="status-detail">
      <span>成功: {{ result.updated }}</span>
      <span>跳过: {{ result.skipped }}</span>
      <span>失败: {{ result.failed }}</span>
      <span>新增: {{ result.new_stocks }}</span>
      <span v-if="result.finished_at">完成于: {{ result.finished_at }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchUpdateStatus, triggerUpdate as apiTriggerUpdate } from '../api'

const status = ref('idle')
const result = ref(null)
const targetDate = ref(new Date().toISOString().slice(0, 10))
let timer = null

const statusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[status.value] || status.value
})

const statusClass = computed(() => status.value)

async function pollStatus() {
  try {
    const { data } = await fetchUpdateStatus()
    status.value = data.status
    result.value = data.result
  } catch {}
}

async function triggerUpdate() {
  await apiTriggerUpdate(targetDate.value || undefined)
  status.value = 'running'
  if (!timer) {
    timer = setInterval(pollStatus, 2000)
  }
}

onMounted(() => {
  pollStatus()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
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
.date-pick { font-size: 13px; }
.date-pick input { padding: 4px 8px; border: 1px solid #dcdfe6; border-radius: 4px; margin-left: 4px; }
button { padding: 6px 16px; cursor: pointer; border: 1px solid #dcdfe6; border-radius: 4px; background: white; }
button:disabled { cursor: not-allowed; opacity: 0.5; }
</style>
