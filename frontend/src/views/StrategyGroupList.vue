<template>
  <div class="group-list-page">
    <div class="page-header">
      <h1>回测</h1>
      <div class="header-actions">
        <button class="btn-primary" @click="$router.push('/backtest/group/create')">+ 创建策略组</button>
        <button class="btn-secondary" @click="doMigrate" :disabled="migrating">{{ migrating ? '迁移中...' : '迁移历史任务' }}</button>
      </div>
    </div>
    <div v-if="migrateMsg" class="migrate-msg">{{ migrateMsg }}</div>
    <div v-if="groups.length" class="group-cards">
      <div v-for="g in groups" :key="g.group_id" class="group-card" @click="$router.push('/backtest/group/' + g.group_id)">
        <div class="card-header">
          <h3>{{ g.name }}</h3>
          <button class="btn-run" @click.stop="openRunDialog(g)">运行</button>
        </div>
        <div class="pipeline-flow">
          <span v-for="(step, i) in g.pipeline" :key="i" class="flow-step">
            <span :class="'freq-badge freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
            <span class="step-name">{{ step.name || step.class_name }}</span>
            <span v-if="i < g.pipeline.length - 1" class="flow-arrow">→</span>
          </span>
        </div>
        <div class="card-footer">
          <span>已运行 {{ g.run_count }} 次</span>
          <span v-if="g.last_run"> | 最近: {{ g.last_run }}</span>
        </div>
      </div>
    </div>
    <p v-else class="empty">暂无策略组，点击「创建策略组」开始</p>
    <div v-if="showRunDialog" class="dialog-overlay" @click.self="showRunDialog = false">
      <div class="dialog">
        <h3>运行策略组: {{ runTarget.name }}</h3>
        <div class="dialog-form">
          <label>开始日期: <input v-model="runStartDate" type="date" min="2010-01-04" /></label>
          <label>结束日期: <input v-model="runEndDate" type="date" min="2010-01-04" /></label>
          <label>执行模式:
            <select v-model="runMode">
              <option value="auto">一键执行</option>
              <option value="stepwise">逐步执行</option>
            </select>
          </label>
        </div>
        <div class="dialog-actions">
          <button class="btn-primary" @click="doRun">开始运行</button>
          <button class="btn-secondary" @click="showRunDialog = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchGroups, runGroup, migrateGroups } from '../api'

const router = useRouter()
const groups = ref([])
const migrating = ref(false)
const migrateMsg = ref('')
const showRunDialog = ref(false)
const runTarget = ref(null)
const runStartDate = ref('')
const runEndDate = ref('')
const runMode = ref('auto')

const freqMap = { daily: '日线', weekly: '周线', monthly: '月线' }
function freqLabel(f) { return freqMap[f] || '日线' }

async function loadGroups() {
  const { data } = await fetchGroups()
  groups.value = data
}

async function doMigrate() {
  migrating.value = true
  migrateMsg.value = ''
  try {
    const { data } = await migrateGroups()
    migrateMsg.value = `迁移完成，共迁移 ${data.migrated} 个策略组`
    loadGroups()
  } catch {
    migrateMsg.value = '迁移失败'
  } finally {
    migrating.value = false
  }
}

function openRunDialog(g) {
  runTarget.value = g
  runStartDate.value = ''
  runEndDate.value = ''
  runMode.value = 'auto'
  showRunDialog.value = true
}

async function doRun() {
  const { data } = await runGroup(runTarget.value.group_id, {
    start_date: runStartDate.value || undefined,
    end_date: runEndDate.value || undefined,
    execution_mode: runMode.value,
  })
  showRunDialog.value = false
  router.push(`/backtest/group/${runTarget.value.group_id}/run/${data.run_id}`)
}

onMounted(loadGroups)
</script>

<style scoped>
.group-list-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header-actions { display: flex; gap: 12px; }
.btn-primary { padding: 8px 16px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-secondary { padding: 8px 16px; background: white; color: #606266; border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-secondary:disabled { color: #c0c4cc; cursor: not-allowed; }
.migrate-msg { padding: 8px 12px; background: #f0f9eb; border: 1px solid #c2e7b0; border-radius: 4px; margin-bottom: 16px; font-size: 13px; color: #67c23a; }
.group-cards { display: flex; flex-direction: column; gap: 16px; }
.group-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 16px; cursor: pointer; transition: box-shadow 0.2s; }
.group-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-header h3 { margin: 0; font-size: 16px; color: #303133; }
.btn-run { padding: 4px 12px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.pipeline-flow { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.flow-step { display: flex; align-items: center; gap: 4px; }
.freq-badge { padding: 2px 6px; border-radius: 3px; font-size: 11px; color: white; }
.freq-daily { background: #909399; }
.freq-weekly { background: #e6a23c; }
.freq-monthly { background: #f56c6c; }
.step-name { font-size: 13px; color: #606266; }
.flow-arrow { color: #c0c4cc; margin: 0 4px; }
.card-footer { margin-top: 12px; font-size: 12px; color: #909399; }
.empty { color: #c0c4cc; font-size: 14px; text-align: center; margin-top: 40px; }
.dialog-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.dialog { background: white; border-radius: 8px; padding: 24px; min-width: 400px; }
.dialog h3 { margin: 0 0 16px; font-size: 16px; }
.dialog-form { display: flex; flex-direction: column; gap: 12px; }
.dialog-form label { font-size: 14px; display: flex; align-items: center; gap: 8px; }
.dialog-form input, .dialog-form select { padding: 4px 8px; }
.dialog-actions { margin-top: 20px; display: flex; gap: 12px; justify-content: flex-end; }
</style>
