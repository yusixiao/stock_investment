# Part 4: Frontend — Strategy List, Screener/Backtest, Results/Compare (Tasks 10-12)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

---

## Task 10: Frontend Scaffolding — Navigation, Routes, API Functions

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/api/index.js`
- Create: `frontend/src/views/StrategyList.vue`
- Modify: `frontend/src/views/StockDetail.vue`

### Steps

- [ ] **Step 1: Update App.vue with navigation bar**

Replace `frontend/src/App.vue`:

```vue
<template>
  <div id="app">
    <nav class="top-nav">
      <router-link to="/">行情</router-link>
      <router-link to="/strategies">策略</router-link>
      <router-link to="/screener">选股</router-link>
      <router-link to="/backtest">回测</router-link>
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

- [ ] **Step 2: Update router with new routes**

Replace `frontend/src/router/index.js`:

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'StockList', component: () => import('../views/StockList.vue') },
  { path: '/stock/:symbol', name: 'StockDetail', component: () => import('../views/StockDetail.vue') },
  { path: '/strategies', name: 'StrategyList', component: () => import('../views/StrategyList.vue') },
  { path: '/screener', name: 'ScreenerPage', component: () => import('../views/ScreenerPage.vue') },
  { path: '/backtest', name: 'BacktestPage', component: () => import('../views/BacktestPage.vue') },
  { path: '/backtest/result/:id', name: 'BacktestResult', component: () => import('../views/BacktestResult.vue') },
  { path: '/compare', name: 'ComparePage', component: () => import('../views/ComparePage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
```

- [ ] **Step 3: Add API functions**

Add to `frontend/src/api/index.js`:

```javascript
export function fetchStrategies() {
  return api.get('/backtest/strategies')
}

export function runBacktest(body) {
  return api.post('/backtest/run', body)
}

export function fetchBacktestStatus(taskId) {
  return api.get(`/backtest/status/${taskId}`)
}

export function fetchBacktestResult(taskId) {
  return api.get(`/backtest/result/${taskId}`)
}

export function runScreener(body) {
  return api.post('/screener/run', body)
}

export function fetchScreenerResult() {
  return api.get('/screener/result')
}
```

- [ ] **Step 4: Create StrategyList.vue**

Create `frontend/src/views/StrategyList.vue`:

```vue
<template>
  <div class="strategy-list-page">
    <h1>策略列表</h1>
    <table class="strategy-table">
      <thead>
        <tr>
          <th>名称</th>
          <th>类型</th>
          <th>描述</th>
          <th>参数</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in strategies" :key="s.class_name">
          <td>{{ s.name }}</td>
          <td><span :class="'badge ' + s.strategy_type">{{ s.strategy_type === 'screener' ? '筛选' : '交易' }}</span></td>
          <td>{{ s.description }}</td>
          <td>{{ formatParams(s.params) }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!strategies.length" class="empty">暂无策略文件，请在 strategies/ 目录中添加 .py 文件</p>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchStrategies } from '../api'

const strategies = ref([])

function formatParams(params) {
  return Object.entries(params).map(([k, v]) => `${k}=${v.default}`).join(', ')
}

async function loadData() {
  const { data } = await fetchStrategies()
  strategies.value = data
}

onMounted(loadData)
</script>

<style scoped>
.strategy-list-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.strategy-table { width: 100%; border-collapse: collapse; margin-top: 16px; }
.strategy-table th, .strategy-table td { padding: 10px; text-align: left; border-bottom: 1px solid #ebeef5; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; color: white; }
.badge.screener { background: #67c23a; }
.badge.trader { background: #e6a23c; }
.empty { color: #909399; text-align: center; margin-top: 40px; }
</style>
```

- [ ] **Step 5: Add adjust toggle to StockDetail.vue**

In `frontend/src/views/StockDetail.vue`, add after the period toggles:

Add `adjust` state in `<script setup>`:

```javascript
const adjust = ref('raw')
const adjustOptions = [
  { value: 'raw', label: '不复权' },
  { value: 'qfq', label: '前复权' },
]
```

Add adjust toggle in template, after the period-toggles `<span>`:

```html
      <span class="period-toggles">
        复权:
        <button v-for="a in adjustOptions" :key="a.value"
          :class="{ active: adjust === a.value }"
          @click="adjust = a.value; loadData()">
          {{ a.label }}
        </button>
      </span>
```

Update `loadData` and `loadIndicators` to include `adjust`:

```javascript
async function loadData() {
  const params = { period: period.value, adjust: adjust.value }
  if (startDate.value) params.start_date = startDate.value
  if (endDate.value) params.end_date = endDate.value
  const { data } = await fetchKline(symbol, params)
  klineData.value = data
  await loadIndicators()
}

async function loadIndicators() {
  if (!selectedIndicators.value.length) {
    indicators.value = {}
    return
  }
  const params = { types: selectedIndicators.value.join(','), period: period.value, adjust: adjust.value }
  if (startDate.value) params.start_date = startDate.value
  if (endDate.value) params.end_date = endDate.value
  const { data } = await fetchIndicators(symbol, params)
  indicators.value = data
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.vue frontend/src/router/index.js frontend/src/api/index.js frontend/src/views/StrategyList.vue frontend/src/views/StockDetail.vue
git commit -m "feat: frontend scaffolding with nav bar, routes, strategy list, adjust toggle"
```

---

## Task 11: Screener + Backtest Pages with Pipeline Builder

**Files:**
- Create: `frontend/src/components/PipelineBuilder.vue`
- Create: `frontend/src/components/ParamEditor.vue`
- Create: `frontend/src/views/ScreenerPage.vue`
- Create: `frontend/src/views/BacktestPage.vue`

### Steps

- [ ] **Step 1: Create PipelineBuilder component**

Create `frontend/src/components/PipelineBuilder.vue`:

```vue
<template>
  <div class="pipeline-builder">
    <div class="available">
      <h3>可用策略</h3>
      <div v-for="s in availableStrategies" :key="s.class_name" class="strategy-card" @click="addToPipeline(s)">
        <span :class="'badge ' + s.strategy_type">{{ s.strategy_type === 'screener' ? '筛选' : '交易' }}</span>
        <span class="name">{{ s.name }}</span>
      </div>
    </div>
    <div class="pipeline">
      <h3>当前管道 <span class="hint" v-if="!pipeline.length">点击左侧策略添加</span></h3>
      <div v-for="(item, idx) in pipeline" :key="idx" class="pipeline-item">
        <span class="step">{{ idx + 1 }}.</span>
        <span :class="'badge ' + item.strategy_type">{{ item.strategy_type === 'screener' ? '筛选' : '交易' }}</span>
        <span class="name">{{ item.name }}</span>
        <button class="remove-btn" @click="removeFromPipeline(idx)">✕</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  strategies: { type: Array, default: () => [] },
  pipeline: { type: Array, default: () => [] },
  mode: { type: String, default: 'backtest' },
})

const emit = defineEmits(['update:pipeline'])

const availableStrategies = computed(() => {
  if (props.mode === 'screener') {
    return props.strategies.filter(s => s.strategy_type === 'screener')
  }
  return props.strategies
})

function addToPipeline(strategy) {
  const hasTrader = props.pipeline.some(s => s.strategy_type === 'trader')
  if (strategy.strategy_type === 'trader' && hasTrader) return
  if (strategy.strategy_type === 'trader') {
    emit('update:pipeline', [...props.pipeline, { ...strategy }])
  } else {
    const traderIdx = props.pipeline.findIndex(s => s.strategy_type === 'trader')
    if (traderIdx >= 0) {
      const newPipeline = [...props.pipeline]
      newPipeline.splice(traderIdx, 0, { ...strategy })
      emit('update:pipeline', newPipeline)
    } else {
      emit('update:pipeline', [...props.pipeline, { ...strategy }])
    }
  }
}

function removeFromPipeline(idx) {
  const newPipeline = props.pipeline.filter((_, i) => i !== idx)
  emit('update:pipeline', newPipeline)
}
</script>

<style scoped>
.pipeline-builder { display: flex; gap: 24px; }
.available, .pipeline { flex: 1; }
.available h3, .pipeline h3 { margin-bottom: 12px; font-size: 14px; color: #606266; }
.hint { color: #c0c4cc; font-weight: normal; font-size: 12px; }
.strategy-card { padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; margin-bottom: 8px; cursor: pointer; display: flex; align-items: center; gap: 8px; }
.strategy-card:hover { border-color: #409eff; background: #ecf5ff; }
.pipeline-item { padding: 8px 12px; border: 1px solid #409eff; border-radius: 4px; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; background: #f0f9ff; }
.step { font-weight: bold; color: #409eff; }
.badge { padding: 2px 6px; border-radius: 3px; font-size: 11px; color: white; }
.badge.screener { background: #67c23a; }
.badge.trader { background: #e6a23c; }
.name { font-size: 13px; }
.remove-btn { margin-left: auto; border: none; background: none; color: #f56c6c; cursor: pointer; font-size: 14px; }
</style>
```

- [ ] **Step 2: Create ParamEditor component**

Create `frontend/src/components/ParamEditor.vue`:

```vue
<template>
  <div class="param-editor" v-if="items.length">
    <h3>参数设置</h3>
    <div v-for="item in items" :key="item.className + '_' + item.paramKey" class="param-row">
      <label>{{ item.strategyName }} → {{ item.paramKey }}</label>
      <input v-model="item.value" @change="emitOverrides" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'

const props = defineProps({
  pipeline: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:overrides'])

const items = ref([])

watch(() => props.pipeline, (pipeline) => {
  items.value = []
  for (const s of pipeline) {
    for (const [key, conf] of Object.entries(s.params || {})) {
      items.value.push({
        className: s.class_name,
        strategyName: s.name,
        paramKey: key,
        value: conf.default,
      })
    }
  }
}, { immediate: true, deep: true })

function emitOverrides() {
  const overrides = {}
  for (const item of items.value) {
    if (!overrides[item.className]) overrides[item.className] = {}
    let val = item.value
    if (!isNaN(Number(val)) && val !== '') val = Number(val)
    overrides[item.className][item.paramKey] = val
  }
  emit('update:overrides', overrides)
}
</script>

<style scoped>
.param-editor { margin-top: 16px; }
.param-editor h3 { font-size: 14px; color: #606266; margin-bottom: 8px; }
.param-row { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.param-row label { font-size: 13px; min-width: 200px; color: #606266; }
.param-row input { padding: 4px 8px; border: 1px solid #dcdfe6; border-radius: 4px; width: 100px; }
</style>
```

- [ ] **Step 3: Create ScreenerPage.vue**

Create `frontend/src/views/ScreenerPage.vue`:

```vue
<template>
  <div class="screener-page">
    <h1>选股</h1>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" mode="screener" />
    <ParamEditor :pipeline="pipeline" @update:overrides="overrides = $event" />
    <button class="run-btn" @click="runScreenerPipeline" :disabled="!pipeline.length || loading">
      {{ loading ? '运行中...' : '运行选股' }}
    </button>
    <div v-if="result" class="result">
      <h2>选股结果 ({{ result.count }} 只)</h2>
      <div class="symbol-grid">
        <span v-for="sym in result.screened_symbols" :key="sym" class="symbol-tag" @click="$router.push('/stock/' + sym)">{{ sym }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchStrategies, runScreener } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'
import ParamEditor from '../components/ParamEditor.vue'

const strategies = ref([])
const pipeline = ref([])
const overrides = ref({})
const result = ref(null)
const loading = ref(false)

async function runScreenerPipeline() {
  loading.value = true
  try {
    const body = {
      pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
      param_overrides: overrides.value,
    }
    const { data } = await runScreener(body)
    result.value = data
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
})
</script>

<style scoped>
.screener-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.run-btn { margin-top: 16px; padding: 10px 24px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.run-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
.result { margin-top: 24px; }
.symbol-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.symbol-tag { padding: 4px 12px; background: #ecf5ff; border: 1px solid #b3d8ff; border-radius: 4px; font-size: 13px; cursor: pointer; }
.symbol-tag:hover { background: #409eff; color: white; }
</style>
```

- [ ] **Step 4: Create BacktestPage.vue**

Create `frontend/src/views/BacktestPage.vue`:

```vue
<template>
  <div class="backtest-page">
    <h1>回测</h1>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" mode="backtest" />
    <ParamEditor :pipeline="pipeline" @update:overrides="overrides = $event" />
    <div class="date-range">
      <label>开始日期: <input v-model="startDate" type="date" /></label>
      <label>结束日期: <input v-model="endDate" type="date" /></label>
    </div>
    <button class="run-btn" @click="runBacktestPipeline" :disabled="!pipeline.length || running">
      {{ running ? '回测运行中...' : '运行回测' }}
    </button>
    <div v-if="taskId" class="status">
      <p>任务ID: {{ taskId }} | 状态: {{ status }}</p>
      <button v-if="status === 'success'" class="view-btn" @click="$router.push('/backtest/result/' + taskId)">查看结果</button>
      <p v-if="status === 'failed'" class="error">回测失败</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { fetchStrategies, runBacktest, fetchBacktestStatus } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'
import ParamEditor from '../components/ParamEditor.vue'

const strategies = ref([])
const pipeline = ref([])
const overrides = ref({})
const startDate = ref('')
const endDate = ref('')
const taskId = ref('')
const status = ref('')
const running = ref(false)
let pollTimer = null

async function runBacktestPipeline() {
  running.value = true
  const body = {
    pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
    param_overrides: overrides.value,
  }
  if (startDate.value) body.start_date = startDate.value
  if (endDate.value) body.end_date = endDate.value
  const { data } = await runBacktest(body)
  taskId.value = data.task_id
  status.value = 'running'
  pollTimer = setInterval(pollStatus, 2000)
}

async function pollStatus() {
  if (!taskId.value) return
  const { data } = await fetchBacktestStatus(taskId.value)
  status.value = data.status
  if (data.status !== 'running') {
    running.value = false
    clearInterval(pollTimer)
  }
}

onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.backtest-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.date-range { margin-top: 16px; display: flex; gap: 16px; }
.date-range label { font-size: 14px; }
.date-range input { padding: 4px 8px; margin-left: 4px; }
.run-btn { margin-top: 16px; padding: 10px 24px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.run-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
.status { margin-top: 16px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.view-btn { margin-top: 8px; padding: 6px 16px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; }
.error { color: #f56c6c; }
</style>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PipelineBuilder.vue frontend/src/components/ParamEditor.vue frontend/src/views/ScreenerPage.vue frontend/src/views/BacktestPage.vue
git commit -m "feat: screener and backtest pages with pipeline builder and param editor"
```

---

## Task 12: Backtest Result Page + Compare Page + Chart Components

**Files:**
- Create: `frontend/src/components/MetricCards.vue`
- Create: `frontend/src/components/EquityCurve.vue`
- Create: `frontend/src/components/DrawdownChart.vue`
- Create: `frontend/src/components/TradeTable.vue`
- Create: `frontend/src/components/BacktestKline.vue`
- Create: `frontend/src/views/BacktestResult.vue`
- Create: `frontend/src/views/ComparePage.vue`

### Steps

- [ ] **Step 1: Create MetricCards component**

Create `frontend/src/components/MetricCards.vue`:

```vue
<template>
  <div class="metric-cards">
    <div class="card" v-for="m in displayMetrics" :key="m.key">
      <div class="label">{{ m.label }}</div>
      <div class="value" :class="m.colorClass">{{ m.display }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ metrics: { type: Object, default: () => ({}) } })

const displayMetrics = computed(() => {
  const m = props.metrics
  if (!m) return []
  return [
    { key: 'total_return', label: '总收益率', display: pct(m.total_return), colorClass: m.total_return >= 0 ? 'up' : 'down' },
    { key: 'annualized_return', label: '年化收益率', display: pct(m.annualized_return), colorClass: m.annualized_return >= 0 ? 'up' : 'down' },
    { key: 'max_drawdown', label: '最大回撤', display: pct(m.max_drawdown), colorClass: 'down' },
    { key: 'sharpe_ratio', label: '夏普比率', display: num(m.sharpe_ratio), colorClass: '' },
    { key: 'win_rate', label: '胜率', display: pct(m.win_rate), colorClass: '' },
    { key: 'profit_loss_ratio', label: '盈亏比', display: num(m.profit_loss_ratio), colorClass: '' },
    { key: 'trade_count', label: '交易次数', display: m.trade_count ?? '-', colorClass: '' },
  ]
})

function pct(v) { return v != null ? (v * 100).toFixed(2) + '%' : '-' }
function num(v) { return v != null ? Number(v).toFixed(2) : '-' }
</script>

<style scoped>
.metric-cards { display: flex; flex-wrap: wrap; gap: 12px; }
.card { padding: 12px 16px; border: 1px solid #ebeef5; border-radius: 6px; min-width: 140px; text-align: center; }
.label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.value { font-size: 20px; font-weight: bold; }
.up { color: #ef5350; }
.down { color: #26a69a; }
</style>
```

- [ ] **Step 2: Create EquityCurve component**

Create `frontend/src/components/EquityCurve.vue`:

```vue
<template>
  <div ref="chartRef" :style="{ width: '100%', height: '350px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  curves: { type: Array, default: () => [] },
})

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.curves.length) return
  const series = props.curves.map((c, i) => ({
    name: c.name || `策略${i + 1}`,
    type: 'line',
    data: c.data.map(d => [d.date, d.total_value]),
    symbol: 'none',
    lineStyle: { width: 1.5 },
  }))
  chart.setOption({
    title: { text: '收益曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 30 }],
    series,
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => props.curves, render, { deep: true })
</script>
```

- [ ] **Step 3: Create DrawdownChart component**

Create `frontend/src/components/DrawdownChart.vue`:

```vue
<template>
  <div ref="chartRef" :style="{ width: '100%', height: '200px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({ equityCurve: { type: Array, default: () => [] } })

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.equityCurve.length) return
  const values = props.equityCurve.map(d => d.total_value)
  let peak = values[0]
  const drawdowns = values.map((v, i) => {
    if (v > peak) peak = v
    const dd = peak > 0 ? -((peak - v) / peak) * 100 : 0
    return [props.equityCurve[i].date, dd]
  })
  chart.setOption({
    title: { text: '回撤曲线', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', formatter: p => `${p[0].axisValue}<br/>回撤: ${p[0].value.toFixed(2)}%` },
    xAxis: { type: 'category' },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'line', data: drawdowns, areaStyle: { color: 'rgba(239,83,80,0.15)' }, lineStyle: { color: '#ef5350', width: 1 }, symbol: 'none' }],
    dataZoom: [{ type: 'inside' }],
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => props.equityCurve, render, { deep: true })
</script>
```

- [ ] **Step 4: Create TradeTable component**

Create `frontend/src/components/TradeTable.vue`:

```vue
<template>
  <div class="trade-table-wrapper">
    <h3>交易明细 ({{ trades.length }} 笔)</h3>
    <table class="trade-table">
      <thead>
        <tr>
          <th>日期</th>
          <th>股票</th>
          <th>方向</th>
          <th>价格</th>
          <th>数量</th>
          <th>金额</th>
          <th>佣金</th>
          <th>印花税</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(t, i) in trades" :key="i">
          <td>{{ t.date }}</td>
          <td>{{ t.symbol }}</td>
          <td :class="t.direction === 'buy' ? 'buy' : 'sell'">{{ t.direction === 'buy' ? '买入' : '卖出' }}</td>
          <td>{{ t.price?.toFixed(2) }}</td>
          <td>{{ t.shares }}</td>
          <td>{{ t.amount?.toFixed(0) }}</td>
          <td>{{ t.commission?.toFixed(2) }}</td>
          <td>{{ t.tax?.toFixed(2) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({ trades: { type: Array, default: () => [] } })
</script>

<style scoped>
.trade-table-wrapper { margin-top: 16px; }
.trade-table-wrapper h3 { font-size: 14px; color: #606266; }
.trade-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.trade-table th, .trade-table td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #ebeef5; }
.buy { color: #ef5350; }
.sell { color: #26a69a; }
</style>
```

- [ ] **Step 5: Create BacktestKline component (placeholder for K-line + trade markers)**

Create `frontend/src/components/BacktestKline.vue`:

```vue
<template>
  <div ref="chartRef" :style="{ width: '100%', height: '400px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  klineData: { type: Array, default: () => [] },
  trades: { type: Array, default: () => [] },
  symbol: { type: String, default: '' },
})

const chartRef = ref(null)
let chart = null

function render() {
  if (!chart || !props.klineData.length) return
  const data = [...props.klineData].sort((a, b) => a.date.localeCompare(b.date))
  const dates = data.map(d => d.date)
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])

  const buyPoints = props.trades
    .filter(t => t.symbol === props.symbol && t.direction === 'buy')
    .map(t => ({ coord: [t.date, t.price], symbol: 'triangle', symbolSize: 10, itemStyle: { color: '#ef5350' } }))

  const sellPoints = props.trades
    .filter(t => t.symbol === props.symbol && t.direction === 'sell')
    .map(t => ({ coord: [t.date, t.price], symbol: 'diamond', symbolSize: 10, itemStyle: { color: '#26a69a' } }))

  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: dates },
    yAxis: { scale: true },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }, { type: 'slider' }],
    series: [{
      type: 'candlestick', data: ohlc,
      itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' },
      markPoint: { data: [...buyPoints, ...sellPoints] },
    }],
  }, true)
}

onMounted(() => { chart = echarts.init(chartRef.value); render(); window.addEventListener('resize', () => chart?.resize()) })
onUnmounted(() => { chart?.dispose() })
watch(() => [props.klineData, props.trades], render, { deep: true })
</script>
```

- [ ] **Step 6: Create BacktestResult.vue**

Create `frontend/src/views/BacktestResult.vue`:

```vue
<template>
  <div class="backtest-result-page">
    <div class="header">
      <button @click="$router.push('/backtest')">返回回测</button>
      <h1>回测结果</h1>
    </div>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="result">
      <MetricCards :metrics="result.metrics" />
      <EquityCurve :curves="[{ name: '策略', data: result.equity_curve }]" />
      <DrawdownChart :equityCurve="result.equity_curve" />
      <TradeTable :trades="result.trades" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchBacktestResult } from '../api'
import MetricCards from '../components/MetricCards.vue'
import EquityCurve from '../components/EquityCurve.vue'
import DrawdownChart from '../components/DrawdownChart.vue'
import TradeTable from '../components/TradeTable.vue'

const route = useRoute()
const taskId = route.params.id
const result = ref(null)
const loading = ref(true)
const error = ref('')

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
</script>

<style scoped>
.backtest-result-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.header button { padding: 6px 12px; cursor: pointer; }
.loading, .error { text-align: center; padding: 40px; color: #909399; }
.error { color: #f56c6c; }
</style>
```

- [ ] **Step 7: Create ComparePage.vue**

Create `frontend/src/views/ComparePage.vue`:

```vue
<template>
  <div class="compare-page">
    <h1>多策略对比</h1>
    <div class="task-list">
      <h3>选择回测结果</h3>
      <div v-for="task in tasks" :key="task.task_id" class="task-item">
        <label>
          <input type="checkbox" :value="task.task_id" v-model="selectedTasks" @change="loadSelectedResults" />
          {{ task.task_id }} ({{ task.status }}) — {{ task.created_at }}
        </label>
      </div>
      <p v-if="!tasks.length" class="empty">暂无回测结果，请先运行回测</p>
    </div>
    <div v-if="results.length">
      <EquityCurve :curves="equityCurves" />
      <h3>指标对比</h3>
      <table class="compare-table">
        <thead>
          <tr>
            <th>任务ID</th>
            <th>总收益率</th>
            <th>年化收益率</th>
            <th>最大回撤</th>
            <th>夏普比率</th>
            <th>胜率</th>
            <th>交易次数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in results" :key="r.task_id">
            <td>{{ r.task_id }}</td>
            <td>{{ pct(r.metrics.total_return) }}</td>
            <td>{{ pct(r.metrics.annualized_return) }}</td>
            <td>{{ pct(r.metrics.max_drawdown) }}</td>
            <td>{{ r.metrics.sharpe_ratio?.toFixed(2) }}</td>
            <td>{{ pct(r.metrics.win_rate) }}</td>
            <td>{{ r.metrics.trade_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { fetchBacktestResult } from '../api'
import EquityCurve from '../components/EquityCurve.vue'

const tasks = ref([])
const selectedTasks = ref([])
const results = ref([])

const equityCurves = computed(() =>
  results.value.map(r => ({ name: r.task_id, data: r.equity_curve }))
)

function pct(v) { return v != null ? (v * 100).toFixed(2) + '%' : '-' }

async function loadSelectedResults() {
  results.value = []
  for (const taskId of selectedTasks.value) {
    try {
      const { data } = await fetchBacktestResult(taskId)
      if (data.status === 'success' && data.result) {
        results.value.push({ task_id: taskId, ...data.result })
      }
    } catch (e) { /* skip */ }
  }
}

onMounted(async () => {
  try {
    const api = (await import('../api')).default
    const { data } = await api.get('/backtest/tasks')
    tasks.value = data
  } catch (e) {
    tasks.value = []
  }
})
</script>

<style scoped>
.compare-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.task-list { margin-bottom: 24px; }
.task-list h3 { font-size: 14px; color: #606266; }
.task-item { padding: 4px 0; }
.task-item label { cursor: pointer; font-size: 13px; display: flex; align-items: center; gap: 8px; }
.empty { color: #909399; font-size: 13px; }
.compare-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
.compare-table th, .compare-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; font-size: 13px; }
</style>
```

- [ ] **Step 8: Add tasks list endpoint to backtest router**

Add to `backend/routers/backtest.py`:

```python
@router.get("/tasks")
def api_list_tasks():
    return task_manager.list_tasks()
```

- [ ] **Step 9: Add fetchBacktestTasks to frontend API**

Add to `frontend/src/api/index.js`:

```javascript
export function fetchBacktestTasks() {
  return api.get('/backtest/tasks')
}
```

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/ frontend/src/views/BacktestResult.vue frontend/src/views/ComparePage.vue backend/routers/backtest.py frontend/src/api/index.js
git commit -m "feat: backtest result page, compare page, and chart components"
```

- [ ] **Step 11: Run all backend tests to ensure no regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 12: Final commit with all remaining changes**

```bash
git add -A
git commit -m "feat: complete screener + backtest system with full Web UI"
```
