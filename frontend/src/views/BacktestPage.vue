<template>
  <div class="min-h-screen flex flex-col">
    <header class="flex-shrink-0 px-4 py-3 border-b border-white/5">
      <div class="flex items-center gap-2 max-w-4xl">
        <div class="flex-1 relative">
          <input
            type="text"
            v-model="codeFilter"
            @keydown.enter="handleFilter"
            placeholder="输入股票代码筛选（留空查看全部）"
            :disabled="isRunning"
            class="input-terminal w-full"
          />
        </div>
        <button @click="handleFilter" :disabled="isLoadingResults" class="btn-secondary flex items-center gap-1.5 whitespace-nowrap">
          筛选
        </button>
        <div class="flex items-center gap-1 whitespace-nowrap">
          <span class="text-xs text-muted">窗口</span>
          <input
            type="number"
            min="1"
            max="120"
            v-model="evalDays"
            placeholder="10"
            :disabled="isRunning"
            class="input-terminal w-14 text-center text-xs py-2"
          />
        </div>
        <button
          @click="forceRerun = !forceRerun"
          :disabled="isRunning"
          class="force-btn flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200 whitespace-nowrap border cursor-pointer"
          :class="forceRerun
            ? 'border-cyan bg-cyan/15 text-cyan shadow-[0_0_12px_rgba(0,212,255,0.25)]'
            : 'border-white/20 bg-white/5 text-secondary hover:border-white/30 hover:text-white'"
        >
          <span
            class="inline-block w-2 h-2 rounded-full transition-colors duration-200"
            :class="forceRerun ? 'bg-cyan shadow-[0_0_6px_rgba(0,212,255,0.8)]' : 'bg-current opacity-40'"
          ></span>
          强制
        </button>
        <button
          @click="handleRun"
          :disabled="isRunning"
          class="btn-primary flex items-center gap-1.5 whitespace-nowrap"
        >
          <svg v-if="isRunning" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
          </svg>
          {{ isRunning ? '运行中...' : '运行回测' }}
        </button>
      </div>
      <div v-if="runResult" class="mt-2 max-w-4xl">
        <div class="flex items-center gap-4 px-3 py-2 rounded-lg bg-elevated border border-white/5 text-xs font-mono animate-fade-in">
          <span class="text-secondary">处理: <span class="text-white">{{ runResult.processed }}</span></span>
          <span class="text-secondary">保存: <span class="text-cyan">{{ runResult.saved }}</span></span>
          <span class="text-secondary">完成: <span class="text-emerald-400">{{ runResult.completed }}</span></span>
        </div>
      </div>
    </header>

    <main class="flex-1 flex overflow-hidden p-3 gap-3">
      <div class="flex flex-col gap-3 w-64 flex-shrink-0 overflow-y-auto">
        <div class="terminal-card p-4 animate-fade-in">
          <div class="mb-3">
            <span class="label-uppercase">整体表现</span>
          </div>
          <div class="space-y-0">
            <div class="flex items-center justify-between py-1.5 border-b border-white/5">
              <span class="text-xs text-secondary">方向准确率</span>
              <span class="text-sm font-mono font-semibold text-cyan">{{ metrics.directionAccuracy }}</span>
            </div>
            <div class="flex items-center justify-between py-1.5 border-b border-white/5">
              <span class="text-xs text-secondary">胜率</span>
              <span class="text-sm font-mono font-semibold text-cyan">{{ metrics.winRate }}</span>
            </div>
            <div class="flex items-center justify-between py-1.5 border-b border-white/5">
              <span class="text-xs text-secondary">平均收益</span>
              <span class="text-sm font-mono font-semibold text-white">{{ metrics.avgReturn }}</span>
            </div>
            <div class="flex items-center justify-between py-1.5 border-b border-white/5">
              <span class="text-xs text-secondary">止损触发率</span>
              <span class="text-sm font-mono font-semibold text-white">{{ metrics.slRate }}</span>
            </div>
            <div class="flex items-center justify-between py-1.5">
              <span class="text-xs text-secondary">止盈触发率</span>
              <span class="text-sm font-mono font-semibold text-white">{{ metrics.tpRate }}</span>
            </div>
          </div>
          <div class="mt-3 pt-2 border-t border-white/5 flex items-center justify-between">
            <span class="text-xs text-muted">评估数量</span>
            <span class="text-xs text-secondary font-mono">{{ metrics.total }}</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-xs text-muted">W / L / N</span>
            <span class="text-xs font-mono">
              <span class="text-emerald-400">{{ metrics.win }}</span> /
              <span class="text-red-400">{{ metrics.loss }}</span> /
              <span class="text-amber-400">{{ metrics.neutral }}</span>
            </span>
          </div>
        </div>
      </div>

      <section class="flex-1 overflow-y-auto">
        <div v-if="isLoadingResults" class="flex flex-col items-center justify-center h-64">
          <div class="w-10 h-10 border-3 border-cyan/20 border-t-cyan rounded-full animate-spin"></div>
          <p class="mt-3 text-secondary text-sm">加载结果中...</p>
        </div>
        <div v-else-if="results.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
          <div class="w-12 h-12 mb-3 rounded-xl bg-elevated flex items-center justify-center">
            <svg class="w-6 h-6 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
            </svg>
          </div>
          <h3 class="text-base font-medium text-white mb-1.5">暂无结果</h3>
          <p class="text-xs text-muted max-w-xs">运行回测以评估历史分析准确度</p>
        </div>
        <div v-else class="animate-fade-in">
          <div class="overflow-x-auto rounded-xl border border-white/5">
            <table class="w-full text-sm">
              <thead>
                <tr class="bg-elevated text-left">
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider">代码</th>
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider">日期</th>
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider">建议</th>
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider">方向</th>
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider">结果</th>
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider text-right">收益%</th>
                  <th class="px-3 py-2.5 text-xs font-medium text-secondary uppercase tracking-wider">状态</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in results"
                  :key="row.id"
                  class="border-t border-white/5 hover:bg-hover transition-colors"
                >
                  <td class="px-3 py-2 font-mono text-cyan text-xs">{{ row.code }}</td>
                  <td class="px-3 py-2 text-xs text-secondary">{{ row.date }}</td>
                  <td class="px-3 py-2 text-xs text-white truncate max-w-[140px]">{{ row.advice }}</td>
                  <td class="px-3 py-2 text-xs">
                    <span :class="row.directionCorrect ? 'text-emerald-400' : 'text-red-400'">
                      {{ row.directionCorrect ? '✓' : '✗' }}
                    </span>
                  </td>
                  <td class="px-3 py-2">
                    <span
                      class="badge"
                      :class="{
                        'badge-success': row.outcome === 'win',
                        'badge-danger': row.outcome === 'loss',
                        'badge-cyan': row.outcome === 'neutral',
                      }"
                    >{{ row.outcome }}</span>
                  </td>
                  <td class="px-3 py-2 text-xs font-mono text-right" :class="row.returnPct > 0 ? 'text-emerald-400' : row.returnPct < 0 ? 'text-red-400' : 'text-secondary'">
                    {{ row.returnPct != null ? row.returnPct.toFixed(1) + '%' : '--' }}
                  </td>
                  <td class="px-3 py-2">
                    <span class="badge badge-success" v-if="row.status === 'completed'">completed</span>
                    <span class="badge badge-cyan" v-else>{{ row.status }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="text-xs text-muted text-center mt-4">共 {{ results.length }} 条结果</p>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const codeFilter = ref('')
const evalDays = ref('')
const forceRerun = ref(false)
const isRunning = ref(false)
const isLoadingResults = ref(false)
const runResult = ref(null)
const results = ref([])

const metrics = ref({
  directionAccuracy: '--',
  winRate: '--',
  avgReturn: '--',
  slRate: '--',
  tpRate: '--',
  total: '0',
  win: '0',
  loss: '0',
  neutral: '0',
})

function handleFilter() {
  // TODO: integrate with backend
}

function handleRun() {
  isRunning.value = true
  setTimeout(() => {
    isRunning.value = false
    runResult.value = { processed: 0, saved: 0, completed: 0 }
  }, 1000)
}
</script>
