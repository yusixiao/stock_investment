<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">回测中心</h1>
      <div class="header-actions">
        <button class="btn-primary" @click="$router.push('/backtest/group/create')">+ 创建策略组</button>
        <button class="btn-secondary" @click="doMigrate" :disabled="migrating">{{ migrating ? '迁移中...' : '迁移历史' }}</button>
      </div>
    </div>

    <div v-if="migrateMsg" class="notice-banner">{{ migrateMsg }}</div>

    <div v-if="groups.length" class="groups-section">
      <div v-if="activeGroups.length" class="group-list">
        <div v-for="g in activeGroups" :key="g.group_id" class="group-card" @click="$router.push('/backtest/group/' + g.group_id)">
          <div class="card-top">
            <h3 class="group-name">{{ g.name }}</h3>
            <div class="card-actions" @click.stop>
              <button class="btn-run" @click="openRunDialog(g)">运行</button>
              <button class="btn-ghost" @click="doArchive(g.group_id, true)">归档</button>
            </div>
          </div>
          <div class="pipeline-flow">
            <span v-for="(step, i) in g.pipeline" :key="i" class="flow-step">
              <span :class="'freq-badge freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
              <span class="step-name">{{ step.name || step.class_name }}</span>
              <span v-if="i < g.pipeline.length - 1" class="flow-arrow">→</span>
            </span>
          </div>
          <div class="card-meta">
            <span>已运行 {{ g.run_count }} 次</span>
            <span v-if="g.last_run"> · 最近: {{ g.last_run }}</span>
          </div>
        </div>
      </div>

      <div v-if="archivedGroups.length" class="archive-section">
        <div class="section-label">已归档 ({{ archivedGroups.length }})</div>
        <div class="group-list">
          <div v-for="g in archivedGroups" :key="g.group_id" class="group-card archived" @click="$router.push('/backtest/group/' + g.group_id)">
            <div class="card-top">
              <h3 class="group-name">{{ g.name }}</h3>
              <button class="btn-ghost" @click.stop="doArchive(g.group_id, false)">恢复</button>
            </div>
            <div class="pipeline-flow">
              <span v-for="(step, i) in g.pipeline" :key="i" class="flow-step">
                <span :class="'freq-badge freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
                <span class="step-name">{{ step.name || step.class_name }}</span>
                <span v-if="i < g.pipeline.length - 1" class="flow-arrow">→</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <p class="empty-text">暂无策略组，点击「创建策略组」开始</p>
    </div>

    <div v-if="showRunDialog" class="dialog-overlay" @click.self="showRunDialog = false">
      <div class="dialog">
        <div class="dialog-header">
          <span class="dialog-title">运行: {{ runTarget.name }}</span>
          <button class="dialog-close" @click="showRunDialog = false">×</button>
        </div>
        <div class="dialog-body">
          <div class="form-group">
            <label class="form-label">开始日期</label>
            <input v-model="runStartDate" type="date" class="form-input" min="2010-01-04" />
          </div>
          <div class="form-group">
            <label class="form-label">结束日期</label>
            <input v-model="runEndDate" type="date" class="form-input" min="2010-01-04" />
          </div>
          <div class="form-group">
            <label class="form-label">执行模式</label>
            <select v-model="runMode" class="form-input">
              <option value="auto">一键执行</option>
              <option value="stepwise">逐步执行</option>
            </select>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-primary" @click="doRun">开始运行</button>
          <button class="btn-secondary" @click="showRunDialog = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchGroups, runGroup, migrateGroups, archiveGroup } from '../api'
import { freqLabel } from '../utils/format'

const router = useRouter()
const groups = ref([])
const migrating = ref(false)
const migrateMsg = ref('')
const showRunDialog = ref(false)
const runTarget = ref(null)
const runStartDate = ref('')
const runEndDate = ref('')
const runMode = ref('auto')

const activeGroups = computed(() => groups.value.filter(g => !g.archived))
const archivedGroups = computed(() => groups.value.filter(g => g.archived))

async function doArchive(groupId, archived) {
  await archiveGroup(groupId, archived)
  loadGroups()
}

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
.header-actions { display: flex; gap: 10px; }

.notice-banner {
  padding: 10px 16px;
  background: var(--st-accent-dim);
  border: 1px solid hsl(190, 100%, 50%, 0.2);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--st-accent);
  margin-bottom: 16px;
}

.groups-section { display: flex; flex-direction: column; gap: 24px; }
.group-list { display: flex; flex-direction: column; gap: 12px; }

.group-card {
  background: var(--st-bg-card);
  border: 1px solid var(--st-border);
  border-radius: var(--radius-xl);
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.group-card:hover {
  border-color: var(--st-border-accent);
  box-shadow: 0 4px 20px hsl(190, 100%, 50%, 0.06);
  transform: translateY(-1px);
}

.group-card.archived { opacity: 0.5; }

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.group-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--st-text-primary);
  margin: 0;
}

.card-actions { display: flex; gap: 8px; }

.btn-run {
  padding: 5px 14px;
  background: linear-gradient(135deg, hsl(152, 69%, 35%), hsl(152, 69%, 45%));
  border: 1px solid hsl(152, 69%, 40%, 0.3);
  border-radius: var(--radius-md);
  color: white;
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px hsl(152, 69%, 40%, 0.2);
}

.btn-run:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
}

.pipeline-flow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.flow-step { display: flex; align-items: center; gap: 4px; }
.step-name { font-size: 12px; color: var(--st-text-secondary); }
.flow-arrow { color: var(--st-text-muted); margin: 0 2px; }

.freq-badge {
  display: inline-block;
  padding: 2px 7px;
  font-size: 10px;
  font-weight: 600;
  border-radius: var(--radius-sm);
}

.freq-daily { background: hsl(152, 69%, 40%, 0.1); color: hsl(152, 69%, 45%); }
.freq-weekly { background: hsl(210, 80%, 50%, 0.1); color: hsl(210, 80%, 60%); }
.freq-monthly { background: hsl(37, 92%, 50%, 0.1); color: hsl(37, 92%, 55%); }

.card-meta {
  font-size: 12px;
  color: var(--st-text-muted);
}

.archive-section { margin-top: 8px; }
.section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--st-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--st-border-light);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
