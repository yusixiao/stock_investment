<template>
  <div class="stock-detail-page">
    <div class="header">
      <button @click="$router.push('/')">返回列表</button>
      <h1>{{ symbol }}</h1>
    </div>

    <div class="controls">
      <label>开始日期: <input v-model="startDate" type="date" @change="loadData" /></label>
      <label>结束日期: <input v-model="endDate" type="date" @change="loadData" /></label>
      <span class="indicator-toggles">
        指标:
        <label v-for="ind in indicatorOptions" :key="ind">
          <input type="checkbox" v-model="selectedIndicators" :value="ind" @change="loadIndicators" />
          {{ ind.toUpperCase() }}
        </label>
      </span>
    </div>

    <KlineChart :kline-data="klineData" :indicators="indicators" :height="chartHeight" />
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { fetchKline, fetchIndicators } from '../api'
import KlineChart from '../components/KlineChart.vue'

const route = useRoute()
const symbol = route.params.symbol
const klineData = ref([])
const indicators = ref({})
const startDate = ref('')
const endDate = ref('')
const selectedIndicators = ref(['ma'])
const indicatorOptions = ['ma', 'macd', 'kdj', 'boll']

const chartHeight = computed(() => {
  let h = 500
  if (selectedIndicators.value.includes('macd')) h += 120
  if (selectedIndicators.value.includes('kdj')) h += 120
  return h
})

async function loadData() {
  const params = {}
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
  const params = { types: selectedIndicators.value.join(',') }
  if (startDate.value) params.start_date = startDate.value
  if (endDate.value) params.end_date = endDate.value
  const { data } = await fetchIndicators(symbol, params)
  indicators.value = data
}

onMounted(loadData)
</script>

<style scoped>
.stock-detail-page { padding: 20px; max-width: 1400px; margin: 0 auto; }
.header { display: flex; align-items: center; gap: 16px; }
.header button { padding: 6px 12px; cursor: pointer; }
.controls { margin: 16px 0; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.controls label { font-size: 14px; }
.controls input[type="date"] { padding: 4px 8px; margin-left: 4px; }
.indicator-toggles { display: flex; align-items: center; gap: 8px; }
.indicator-toggles label { display: flex; align-items: center; gap: 4px; cursor: pointer; }
</style>
