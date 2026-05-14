<template>
  <div class="min-h-full flex flex-col rounded-[1.5rem] bg-transparent">
    <header class="flex-shrink-0 border-b border-white/5 px-3 py-3 sm:px-4">
      <div class="flex max-w-5xl flex-wrap items-center gap-2">
        <div class="relative min-w-0 flex-[1_1_220px]">
          <input
            type="text"
            v-model="searchQuery"
            @keydown.enter="handleFilter"
            placeholder="搜索策略组名称..."
            class="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none"
          />
        </div>
        <button
          type="button"
          @click="handleFilter"
          class="btn-secondary flex items-center gap-1.5 whitespace-nowrap"
        >
          筛选
        </button>
        <button
          type="button"
          @click="showArchived = !showArchived"
          :class="['backtest-force-btn', showArchived ? 'active' : '']"
        >
          <span class="dot"></span>
          已归档
        </button>
        <button
          type="button"
          @click="$router.push('/backtest/group/create')"
          class="btn-primary flex items-center gap-1.5 whitespace-nowrap"
        >
          + 创建策略组
        </button>
      </div>
      <p class="mt-2 text-xs" style="color: var(--text-muted)">
        策略组管理 · 创建策略 Pipeline 并运行回测
      </p>
    </header>

    <main class="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3 lg:flex-row">
      <div class="flex max-h-[38vh] flex-col gap-3 overflow-y-auto lg:max-h-none lg:w-60 lg:flex-shrink-0">
        <div v-if="loading" class="flex items-center justify-center py-8">
          <div class="backtest-spinner sm"></div>
        </div>
        <div v-else-if="stats" class="perf-card animate-fade-in">
          <div class="mb-3">
            <span class="label-uppercase">总体统计</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">策略组</span>
            <span class="value accent">{{ stats.totalGroups }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">总运行次数</span>
            <span class="value">{{ stats.totalRuns }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">活跃</span>
            <span class="value accent">{{ stats.activeGroups }}</span>
          </div>
          <div class="backtest-metric-row">
            <span class="label">已归档</span>
            <span class="value">{{ stats.archivedGroups }}</span>
          </div>
          <div class="backtest-metric-footer">
            <span class="text-xs" style="color: var(--text-muted)">策略文件</span>
            <span class="text-xs font-mono" style="color: var(--text-secondary)">{{ stats.totalStrategies }}</span>
          </div>
        </div>
      </div>

      <section class="min-h-0 flex-1 overflow-y-auto">
        <div v-if="loading" class="flex flex-col items-center justify-center h-64">
          <div class="backtest-spinner md"></div>
          <p class="mt-3 text-sm" style="color: var(--text-secondary)">加载中...</p>
        </div>
        <div v-else-if="filteredGroups.length === 0" class="backtest-empty-state">
          <div class="icon-wrap">
            <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </div>
          <div class="title">暂无策略组</div>
          <div class="desc">点击「创建策略组」开始构建你的第一个回测 Pipeline</div>
        </div>
        <div v-else class="animate-fade-in">
          <div class="backtest-table-toolbar">
            <div class="backtest-table-toolbar-meta">
              <span class="label-uppercase">策略组列表</span>
              <span class="text-xs" style="color: var(--text-secondary)">
                {{ showArchived ? '已归档' : '活跃' }} · {{ filteredGroups.length }} 个策略组
              </span>
            </div>
          </div>
          <div class="backtest-table-wrapper">
            <table class="backtest-table min-w-[700px] w-full text-sm">
              <thead class="backtest-table-head">
                <tr class="text-left">
                  <th class="backtest-table-head-cell">名称</th>
                  <th class="backtest-table-head-cell">Pipeline</th>
                  <th class="backtest-table-head-cell">运行次数</th>
                  <th class="backtest-table-head-cell">最近运行</th>
                  <th class="backtest-table-head-cell">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="g in filteredGroups"
                  :key="g.group_id"
                  class="backtest-table-row cursor-pointer"
                  @click="$router.push('/backtest/group/' + g.group_id)"
                >
                  <td class="backtest-table-cell backtest-table-code">
                    {{ g.name }}
                  </td>
                  <td class="backtest-table-cell">
                    <div class="flex flex-wrap items-center gap-1">
                      <span
                        v-for="(step, i) in g.pipeline"
                        :key="i"
                        class="inline-flex items-center gap-1"
                      >
                        <span :class="freqBadgeClass(step.frequency)">{{ freqLabel(step.frequency) }}</span>
                        <span class="text-xs" style="color: var(--text-secondary)">{{ step.name || step.class_name }}</span>
                        <span v-if="i < g.pipeline.length - 1" class="text-xs" style="color: var(--text-muted)">→</span>
                      </span>
                    </div>
                  </td>
                  <td class="backtest-table-cell">
                    <span class="font-mono" style="color: var(--color-cyan)">{{ g.run_count }}</span>
                  </td>
                  <td class="backtest-table-cell" style="color: var(--text-secondary)">
                    {{ g.last_run || '--' }}
                  </td>
                  <td class="backtest-table-cell" @click.stop>
                    <div class="flex items-center gap-2">
                      <button class="backtest-force-btn" @click="openRunDialog(g)">运行</button>
                      <button class="backtest-force-btn" @click="doArchive(g.group_id, !showArchived)">
                        {{ showArchived ? '恢复' : '归档' }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>

    <div v-if="runDialog" class="dialog-overlay" @click.self="runDialog = null">
      <div class="dialog">
        <div class="dialog-header">
          <span class="dialog-title">运行回测 - {{ runDialog.name }}</span>
          <button class="dialog-close" @click="runDialog = null">&times;</button>
        </div>
        <div class="dialog-body">
          <div>
            <label class="form-label">开始日期</label>
            <input v-model="runForm.start_date" type="date" class="form-input w-full mt-1" />
          </div>
          <div>
            <label class="form-label">结束日期</label>
            <input v-model="runForm.end_date" type="date" class="form-input w-full mt-1" />
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-secondary" @click="runDialog = null">取消</button>
          <button class="btn-primary" @click="doRun" :disabled="running">
            {{ running ? '运行中...' : '开始运行' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchGroups, fetchStrategies, archiveGroup, runGroup } from '../api/index.js'

const router = useRouter()
const groups = ref([])
const strategies = ref([])
const loading = ref(true)
const searchQuery = ref('')
const showArchived = ref(false)
const runDialog = ref(null)
const runForm = ref({ start_date: '', end_date: '' })
const running = ref(false)

const stats = computed(() => {
  if (!groups.value.length && !strategies.value.length) return null
  const active = groups.value.filter(g => !g.archived)
  const archived = groups.value.filter(g => g.archived)
  return {
    totalGroups: groups.value.length,
    activeGroups: active.length,
    archivedGroups: archived.length,
    totalRuns: groups.value.reduce((sum, g) => sum + (g.run_count || 0), 0),
    totalStrategies: strategies.value.length,
  }
})

const filteredGroups = computed(() => {
  let list = groups.value.filter(g => showArchived.value ? g.archived : !g.archived)
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    list = list.filter(g => g.name.toLowerCase().includes(q))
  }
  return list
})

function handleFilter() {}

function freqLabel(freq) {
  const map = { daily: '日', weekly: '周', monthly: '月' }
  return map[freq] || '日'
}

function freqBadgeClass(freq) {
  const base = 'inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold'
  const colors = {
    daily: 'bg-gray-500/20 text-gray-400',
    weekly: 'bg-amber-500/20 text-amber-400',
    monthly: 'bg-rose-500/20 text-rose-400',
  }
  return `${base} ${colors[freq] || colors.daily}`
}

function openRunDialog(g) {
  runDialog.value = g
  runForm.value = { start_date: '', end_date: '' }
}

async function doRun() {
  if (!runDialog.value) return
  running.value = true
  try {
    const res = await runGroup(runDialog.value.group_id, runForm.value)
    runDialog.value = null
    router.push(`/backtest/group/${res.data.group_id}/run/${res.data.run_id}`)
  } catch (e) {
    alert('运行失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    running.value = false
  }
}

async function doArchive(groupId, archived) {
  try {
    await archiveGroup(groupId, archived)
    await loadData()
  } catch (e) {
    console.error(e)
  }
}

async function loadData() {
  try {
    const [gRes, sRes] = await Promise.all([fetchGroups(), fetchStrategies()])
    groups.value = gRes.data || []
    strategies.value = sRes.data || []
  } catch (e) {
    groups.value = []
    strategies.value = []
  }
  loading.value = false
}

onMounted(loadData)
</script>
