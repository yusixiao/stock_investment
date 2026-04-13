<template>
  <div class="portfolio-detail-page">
    <div class="header">
      <button @click="$router.push('/portfolio')">返回列表</button>
      <h1>{{ portfolio?.name || '' }}</h1>
      <button class="btn-danger" @click="onDelete">删除组合</button>
    </div>

    <div v-if="portfolio" class="summary-cards">
      <div class="metric-card">
        <div class="metric-label">总市值</div>
        <div class="metric-value primary">¥ {{ formatNum(portfolio.total_value) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">可用现金</div>
        <div class="metric-value">¥ {{ formatNum(portfolio.cash) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">持仓市值</div>
        <div class="metric-value">¥ {{ formatNum(portfolio.market_value) }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">总收益率</div>
        <div class="metric-value" :class="portfolio.total_return >= 0 ? 'up' : 'down'">
          {{ (portfolio.total_return * 100).toFixed(2) }}%
        </div>
      </div>
    </div>

    <div class="section">
      <h2>持仓明细</h2>
      <table class="data-table" v-if="holdings.length">
        <thead>
          <tr><th>股票</th><th>持有</th><th>成本价</th><th>市值</th></tr>
        </thead>
        <tbody>
          <tr v-for="h in holdings" :key="h.symbol">
            <td>{{ h.symbol }}</td>
            <td>{{ h.shares }}</td>
            <td>{{ h.avg_cost.toFixed(2) }}</td>
            <td>{{ formatNum(h.market_value) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无持仓</div>
    </div>

    <div class="section" v-if="snapshots.length">
      <PortfolioEquity :snapshots="snapshots" />
    </div>

    <div class="section">
      <div class="section-header">
        <h2>交易记录</h2>
        <button class="btn-primary" @click="showTradeForm = true">+ 录入交易</button>
      </div>
      <table class="data-table" v-if="trades.length">
        <thead>
          <tr><th>日期</th><th>股票</th><th>方向</th><th>价格</th><th>数量</th><th>佣金</th><th>印花税</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in trades" :key="t.id">
            <td>{{ t.trade_date }}</td>
            <td>{{ t.symbol }}</td>
            <td><span class="dir-tag" :class="t.direction">{{ t.direction === 'buy' ? '买入' : '卖出' }}</span></td>
            <td>{{ t.price.toFixed(2) }}</td>
            <td>{{ t.shares }}</td>
            <td>{{ t.commission.toFixed(2) }}</td>
            <td>{{ t.tax.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无交易记录</div>
    </div>

    <TradeForm
      v-if="showTradeForm"
      @submit="onTrade"
      @close="showTradeForm = false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getPortfolio, getHoldings, getTrades, getSnapshots, addTrade, deletePortfolio } from '../api'
import TradeForm from '../components/TradeForm.vue'
import PortfolioEquity from '../components/PortfolioEquity.vue'

const route = useRoute()
const router = useRouter()
const id = route.params.id

const portfolio = ref(null)
const holdings = ref([])
const trades = ref([])
const snapshots = ref([])
const showTradeForm = ref(false)

async function load() {
  const [pRes, hRes, tRes, sRes] = await Promise.all([
    getPortfolio(id),
    getHoldings(id),
    getTrades(id),
    getSnapshots(id),
  ])
  portfolio.value = pRes.data
  holdings.value = hRes.data
  trades.value = tRes.data
  snapshots.value = sRes.data
}

async function onTrade(form) {
  await addTrade(id, form)
  showTradeForm.value = false
  await load()
}

async function onDelete() {
  if (!confirm('确定删除此组合？')) return
  await deletePortfolio(id)
  router.push('/portfolio')
}

function formatNum(n) {
  return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

onMounted(load)
</script>

<style scoped>
.portfolio-detail-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.header h1 { flex: 1; font-size: 20px; margin: 0; }
.header button { padding: 6px 12px; cursor: pointer; }
.btn-primary { background: #409eff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-danger { background: #f56c6c; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
.summary-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
.metric-card { background: #f5f7fa; border-radius: 8px; padding: 16px; text-align: center; }
.metric-label { font-size: 13px; color: #909399; margin-bottom: 4px; }
.metric-value { font-size: 20px; font-weight: bold; }
.metric-value.primary { color: #409eff; }
.metric-value.up { color: #67c23a; }
.metric-value.down { color: #f56c6c; }
.section { margin-bottom: 24px; }
.section h2 { font-size: 16px; margin-bottom: 12px; }
.section-header { display: flex; justify-content: space-between; align-items: center; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; padding: 10px 8px; border-bottom: 2px solid #ebeef5; color: #909399; font-weight: normal; }
.data-table td { padding: 10px 8px; border-bottom: 1px solid #ebeef5; }
.dir-tag { font-size: 12px; padding: 2px 8px; border-radius: 4px; }
.dir-tag.buy { background: #fef0f0; color: #f56c6c; }
.dir-tag.sell { background: #f0f9eb; color: #67c23a; }
.empty { text-align: center; padding: 24px; color: #909399; }
</style>
