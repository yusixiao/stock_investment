<template>
  <div class="portfolio-list-page">
    <div class="header">
      <h1>我的组合</h1>
      <button class="btn-primary" @click="showCreate = true">+ 新建组合</button>
    </div>

    <div v-if="showCreate" class="create-form">
      <input v-model="newName" placeholder="组合名称" class="input" />
      <input v-model.number="newCapital" type="number" placeholder="初始资金" class="input" />
      <button class="btn-primary" @click="onCreate">创建</button>
      <button class="btn-secondary" @click="showCreate = false">取消</button>
    </div>

    <div class="cards">
      <div
        v-for="p in portfolios"
        :key="p.id"
        class="card"
        @click="$router.push(`/portfolio/${p.id}`)"
      >
        <div class="card-top">
          <span class="card-name">{{ p.name }}</span>
          <span class="tag" :class="p.source">{{ p.source === 'manual' ? '手动' : '回测' }}</span>
        </div>
        <div class="card-value">¥ {{ formatNum(p.initial_capital) }}</div>
      </div>
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
.portfolio-list-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header h1 { font-size: 20px; margin: 0; }
.btn-primary { background: #409eff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-secondary { background: #dcdfe6; color: #606266; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.create-form { display: flex; gap: 8px; margin-bottom: 20px; align-items: center; }
.input { padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.card { border: 1px solid #ebeef5; border-radius: 8px; padding: 20px; cursor: pointer; transition: box-shadow 0.2s; }
.card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-name { font-weight: bold; font-size: 16px; }
.tag { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
.tag.manual { background: #f0f9eb; color: #67c23a; }
.tag.backtest { background: #ecf5ff; color: #409eff; }
.card-value { font-size: 24px; font-weight: bold; color: #409eff; }
</style>
