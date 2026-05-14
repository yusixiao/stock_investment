<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">我的组合</h1>
      <button class="btn-primary" @click="showCreate = true">+ 新建组合</button>
    </div>

    <div v-if="showCreate" class="create-card">
      <div class="form-group">
        <label class="form-label">组合名称</label>
        <input v-model="newName" class="form-input" placeholder="输入名称" />
      </div>
      <div class="form-group">
        <label class="form-label">初始资金</label>
        <input v-model.number="newCapital" type="number" class="form-input" placeholder="100000" />
      </div>
      <div class="form-actions">
        <button class="btn-primary" @click="onCreate">创建</button>
        <button class="btn-secondary" @click="showCreate = false">取消</button>
      </div>
    </div>

    <div v-if="portfolios.length" class="portfolio-grid">
      <div v-for="p in portfolios" :key="p.id" class="portfolio-card" @click="$router.push(`/portfolio/${p.id}`)">
        <div class="card-top">
          <span class="port-name">{{ p.name }}</span>
          <span :class="'source-badge source-' + p.source">{{ p.source === 'manual' ? '手动' : '回测' }}</span>
        </div>
        <div class="card-value">¥ {{ formatNum(p.initial_capital) }}</div>
      </div>
    </div>
    <div v-else class="empty-state">
      <p class="empty-text">暂无组合，点击「新建组合」开始</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { listPortfolios, createPortfolio } from '../api'

const portfolios = ref([])
const showCreate = ref(false)
const newName = ref('')
const newCapital = ref(100000)

async function load() {
  const { data } = await listPortfolios()
  portfolios.value = data
}

async function onCreate() {
  if (!newName.value) return
  await createPortfolio({ name: newName.value, initial_capital: newCapital.value })
  showCreate.value = false
  newName.value = ''
  newCapital.value = 100000
  await load()
}

function formatNum(n) {
  return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

onMounted(load)
</script>

<style scoped>
.create-card {
  background: var(--st-bg-card);
  border: 1px solid var(--st-border);
  border-radius: var(--radius-xl);
  padding: 20px;
  margin-bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-actions { display: flex; gap: 10px; margin-top: 4px; }

.portfolio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.portfolio-card {
  background: var(--st-bg-card);
  border: 1px solid var(--st-border);
  border-radius: var(--radius-xl);
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.portfolio-card:hover {
  border-color: var(--st-border-accent);
  box-shadow: 0 4px 20px hsl(190, 100%, 50%, 0.06);
  transform: translateY(-2px);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.port-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--st-text-primary);
}

.source-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
}

.source-manual { background: hsl(152, 69%, 40%, 0.1); color: hsl(152, 69%, 45%); }
.source-backtest { background: var(--st-accent-dim); color: var(--st-accent); }

.card-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--st-accent);
  font-family: var(--font-mono);
}
</style>
