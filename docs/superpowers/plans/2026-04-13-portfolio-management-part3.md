# Portfolio Management — Part 3: Frontend (Tasks 6-9)

Parent plan: `docs/superpowers/plans/2026-04-13-portfolio-management.md`

---

### Task 6: Frontend API + Routing + Nav

**Files:**
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add portfolio API functions**

In `frontend/src/api/index.js`, add before the `export default api` line:

```javascript
export function createPortfolio(body) {
  return api.post('/portfolio/', body)
}

export function listPortfolios() {
  return api.get('/portfolio/')
}

export function getPortfolio(id) {
  return api.get(`/portfolio/${id}`)
}

export function deletePortfolio(id) {
  return api.delete(`/portfolio/${id}`)
}

export function addTrade(portfolioId, body) {
  return api.post(`/portfolio/${portfolioId}/trades`, body)
}

export function getTrades(portfolioId) {
  return api.get(`/portfolio/${portfolioId}/trades`)
}

export function getHoldings(portfolioId) {
  return api.get(`/portfolio/${portfolioId}/holdings`)
}

export function getSnapshots(portfolioId) {
  return api.get(`/portfolio/${portfolioId}/snapshots`)
}

export function importFromBacktest(taskId, body) {
  return api.post(`/portfolio/import/${taskId}`, body)
}
```

- [ ] **Step 2: Add portfolio routes**

Replace `frontend/src/router/index.js` with:

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'StockList', component: () => import('../views/StockList.vue') },
  { path: '/stock/:symbol', name: 'StockDetail', component: () => import('../views/StockDetail.vue') },
  { path: '/strategies', name: 'StrategyList', component: () => import('../views/StrategyList.vue') },
  { path: '/screener', name: 'ScreenerPage', component: () => import('../views/ScreenerPage.vue') },
  { path: '/backtest', name: 'BacktestPage', component: () => import('../views/BacktestPage.vue') },
  { path: '/backtest/result/:id', name: 'BacktestResult', component: () => import('../views/BacktestResult.vue') },
  { path: '/portfolio', name: 'PortfolioList', component: () => import('../views/PortfolioList.vue') },
  { path: '/portfolio/:id', name: 'PortfolioDetail', component: () => import('../views/PortfolioDetail.vue') },
  { path: '/compare', name: 'ComparePage', component: () => import('../views/ComparePage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
```

- [ ] **Step 3: Add nav link**

Replace `frontend/src/App.vue` with:

```vue
<template>
  <div id="app">
    <nav class="top-nav">
      <router-link to="/">行情</router-link>
      <router-link to="/strategies">策略</router-link>
      <router-link to="/screener">选股</router-link>
      <router-link to="/backtest">回测</router-link>
      <router-link to="/portfolio">持仓</router-link>
      <router-link to="/compare">对比</router-link>
    </nav>
    <router-view />
  </div>
</template>

<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.top-nav { display: flex; gap: 0; background: #409eff; padding: 0; }
.top-nav a { color: white; text-decoration: none; padding: 12px 20px; font-size: 14px; transition: background 0.2s; }
.top-nav a:hover { background: rgba(255,255,255,0.15); }
.top-nav a.router-link-active { background: rgba(255,255,255,0.25); font-weight: bold; }
</style>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/index.js frontend/src/router/index.js frontend/src/App.vue
git commit -m "feat(portfolio): add frontend API functions, routes, and nav link"
```

---

### Task 7: PortfolioList Page

**Files:**
- Create: `frontend/src/views/PortfolioList.vue`

- [ ] **Step 1: Create PortfolioList.vue**

Create `frontend/src/views/PortfolioList.vue`:

```vue
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
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/PortfolioList.vue
git commit -m "feat(portfolio): add PortfolioList page with create form"
```

---

### Task 8: PortfolioDetail Page + TradeForm + PortfolioEquity

**Files:**
- Create: `frontend/src/components/TradeForm.vue`
- Create: `frontend/src/components/PortfolioEquity.vue`
- Create: `frontend/src/views/PortfolioDetail.vue`

- [ ] **Step 1: Create TradeForm.vue**

Create `frontend/src/components/TradeForm.vue`:

```vue
<template>
  <div class="trade-form-overlay" @click.self="$emit('close')">
    <div class="trade-form">
      <h3>录入交易</h3>
      <div class="form-row">
        <label>股票代码</label>
        <input v-model="form.symbol" placeholder="如 600519.SH" class="input" />
      </div>
      <div class="form-row">
        <label>方向</label>
        <select v-model="form.direction" class="input">
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
      </div>
      <div class="form-row">
        <label>价格</label>
        <input v-model.number="form.price" type="number" step="0.01" class="input" />
      </div>
      <div class="form-row">
        <label>数量（股）</label>
        <input v-model.number="form.shares" type="number" step="100" class="input" />
      </div>
      <div class="form-row">
        <label>日期</label>
        <input v-model="form.trade_date" type="date" class="input" />
      </div>
      <div class="form-actions">
        <button class="btn-primary" @click="onSubmit">提交</button>
        <button class="btn-secondary" @click="$emit('close')">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const emit = defineEmits(['submit', 'close'])

const today = new Date().toISOString().slice(0, 10)
const form = reactive({
  symbol: '',
  direction: 'buy',
  price: 0,
  shares: 100,
  trade_date: today,
})

function onSubmit() {
  if (!form.symbol || form.price <= 0 || form.shares <= 0) return
  emit('submit', { ...form })
}
</script>

<style scoped>
.trade-form-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.trade-form { background: white; border-radius: 8px; padding: 24px; width: 400px; }
.trade-form h3 { margin: 0 0 16px; }
.form-row { margin-bottom: 12px; }
.form-row label { display: block; font-size: 13px; color: #606266; margin-bottom: 4px; }
.input { width: 100%; padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; box-sizing: border-box; }
.form-actions { display: flex; gap: 8px; margin-top: 16px; }
.btn-primary { background: #409eff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-secondary { background: #dcdfe6; color: #606266; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
</style>
```

- [ ] **Step 2: Create PortfolioEquity.vue**

Create `frontend/src/components/PortfolioEquity.vue`:

```vue
<template>
  <div ref="chartRef" :style="{ width: '100%', height: '350px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  snapshots: { type: Array, default: () => [] },
})

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.snapshots.length) return
  chart.setOption({
    title: { text: '收益曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 30 }],
    series: [{
      type: 'line',
      data: props.snapshots.map(s => [s.date, s.total_value]),
      symbol: 'none',
      lineStyle: { width: 1.5 },
      areaStyle: { opacity: 0.1 },
    }],
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => props.snapshots, render, { deep: true })
</script>
```

- [ ] **Step 3: Create PortfolioDetail.vue**

Create `frontend/src/views/PortfolioDetail.vue`:

```vue
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
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TradeForm.vue frontend/src/components/PortfolioEquity.vue frontend/src/views/PortfolioDetail.vue
git commit -m "feat(portfolio): add PortfolioDetail page with TradeForm and PortfolioEquity"
```

---

### Task 9: BacktestResult Import Button

**Files:**
- Modify: `frontend/src/views/BacktestResult.vue`

- [ ] **Step 1: Add import button to BacktestResult.vue**

Replace `frontend/src/views/BacktestResult.vue` with:

```vue
<template>
  <div class="backtest-result-page">
    <div class="header">
      <button @click="$router.push('/backtest')">返回回测</button>
      <h1>回测结果</h1>
      <button v-if="result" class="btn-import" @click="showImport = true">导入持仓</button>
    </div>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="result">
      <MetricCards :metrics="result.metrics" />
      <EquityCurve :curves="[{ name: '策略', data: result.equity_curve }]" />
      <DrawdownChart :equityCurve="result.equity_curve" />
      <TradeTable :trades="result.trades" />
    </div>

    <div v-if="showImport" class="import-overlay" @click.self="showImport = false">
      <div class="import-form">
        <h3>导入持仓为新组合</h3>
        <input v-model="importName" placeholder="组合名称" class="input" />
        <div class="import-actions">
          <button class="btn-primary" @click="onImport">确认导入</button>
          <button class="btn-secondary" @click="showImport = false">取消</button>
        </div>
        <div v-if="importError" class="import-error">{{ importError }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchBacktestResult, importFromBacktest } from '../api'
import MetricCards from '../components/MetricCards.vue'
import EquityCurve from '../components/EquityCurve.vue'
import DrawdownChart from '../components/DrawdownChart.vue'
import TradeTable from '../components/TradeTable.vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id
const result = ref(null)
const loading = ref(true)
const error = ref('')
const showImport = ref(false)
const importName = ref('')
const importError = ref('')

onMounted(async () => {
  try {
    const { data } = await fetchBacktestResult(taskId)
    if (data.status === 'success') {
      result.value = data.result
    } else if (data.status === 'failed') {
      error.value = data.error || '回测失败'
    } else {
      error.value = '回测尚未完成'
    }
  } catch (e) {
    error.value = '加载失败'
  } finally {
    loading.value = false
  }
})

async function onImport() {
  if (!importName.value) return
  importError.value = ''
  try {
    const { data } = await importFromBacktest(taskId, { name: importName.value })
    showImport.value = false
    router.push(`/portfolio/${data.id}`)
  } catch (e) {
    importError.value = e.response?.data?.detail || '导入失败'
  }
}
</script>

<style scoped>
.backtest-result-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.header h1 { flex: 1; }
.header button { padding: 6px 12px; cursor: pointer; }
.btn-import { background: #67c23a; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
.btn-primary { background: #409eff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-secondary { background: #dcdfe6; color: #606266; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.loading, .error { text-align: center; padding: 40px; color: #909399; }
.error { color: #f56c6c; }
.import-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.import-form { background: white; border-radius: 8px; padding: 24px; width: 360px; }
.import-form h3 { margin: 0 0 16px; }
.input { width: 100%; padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; box-sizing: border-box; }
.import-actions { display: flex; gap: 8px; margin-top: 16px; }
.import-error { color: #f56c6c; margin-top: 8px; font-size: 13px; }
</style>
```

- [ ] **Step 2: Run all backend tests to confirm nothing is broken**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/BacktestResult.vue
git commit -m "feat(portfolio): add import button to BacktestResult page"
```
