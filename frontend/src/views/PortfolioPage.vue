<template>
  <div class="min-h-screen px-4 pb-6 pt-4 md:px-6">
    <header class="mb-6 flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-white mb-1">持仓管理</h1>
        <p class="text-sm text-secondary">跟踪投资组合，监控持仓表现。</p>
      </div>
      <button class="btn-primary flex items-center gap-1.5" @click="showCreateModal = true">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
        </svg>
        新建组合
      </button>
    </header>

    <div v-if="portfolios.length === 0" class="flex flex-col items-center justify-center py-20 text-center">
      <div class="w-16 h-16 mb-4 rounded-2xl bg-white/5 flex items-center justify-center">
        <svg class="w-8 h-8 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 7H4a2 2 0 00-2 2v10a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2z"/>
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16"/>
        </svg>
      </div>
      <h3 class="text-lg font-medium text-white mb-2">暂无持仓组合</h3>
      <p class="text-sm text-secondary max-w-sm">创建您的第一个投资组合，开始跟踪持仓表现。</p>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="p in portfolios"
        :key="p.id"
        class="terminal-card terminal-card-hover p-5 cursor-pointer"
      >
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-semibold text-white">{{ p.name }}</h3>
          <span class="badge badge-cyan">{{ p.stockCount }} 只</span>
        </div>
        <div class="space-y-2">
          <div class="flex justify-between">
            <span class="text-xs text-secondary">总市值</span>
            <span class="text-sm font-mono text-white">¥{{ formatNum(p.totalValue) }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-xs text-secondary">总收益</span>
            <span class="text-sm font-mono" :class="p.totalReturn >= 0 ? 'text-emerald-400' : 'text-red-400'">
              {{ p.totalReturn >= 0 ? '+' : '' }}{{ p.totalReturn.toFixed(2) }}%
            </span>
          </div>
          <div class="flex justify-between">
            <span class="text-xs text-secondary">今日收益</span>
            <span class="text-sm font-mono" :class="p.todayReturn >= 0 ? 'text-emerald-400' : 'text-red-400'">
              {{ p.todayReturn >= 0 ? '+' : '' }}{{ p.todayReturn.toFixed(2) }}%
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Modal Placeholder -->
    <div v-if="showCreateModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center" @click.self="showCreateModal = false">
      <div class="glass-card p-6 w-full max-w-md animate-slide-up">
        <h2 class="text-lg font-semibold text-white mb-4">新建投资组合</h2>
        <div class="space-y-4">
          <div>
            <label class="text-xs text-secondary mb-1 block">组合名称</label>
            <input type="text" v-model="newPortfolioName" class="input-terminal" placeholder="例如：核心持仓"/>
          </div>
          <div>
            <label class="text-xs text-secondary mb-1 block">初始资金</label>
            <input type="number" v-model="newPortfolioCapital" class="input-terminal" placeholder="100000"/>
          </div>
        </div>
        <div class="flex justify-end gap-3 mt-6">
          <button class="btn-secondary" @click="showCreateModal = false">取消</button>
          <button class="btn-primary" @click="createPortfolio">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const portfolios = ref([
  { id: 1, name: '核心持仓', stockCount: 5, totalValue: 523800, totalReturn: 12.35, todayReturn: 0.82 },
  { id: 2, name: '短线策略', stockCount: 3, totalValue: 156200, totalReturn: -2.15, todayReturn: -1.23 },
])

const showCreateModal = ref(false)
const newPortfolioName = ref('')
const newPortfolioCapital = ref(100000)

function formatNum(n) {
  return n.toLocaleString('zh-CN')
}

function createPortfolio() {
  // TODO: integrate with backend
  showCreateModal.value = false
}
</script>
