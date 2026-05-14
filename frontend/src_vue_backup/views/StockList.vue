<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">行情总览</h1>
        <p class="page-subtitle">{{ total }} 只股票 · 最新日期 {{ stocks.length ? stocks[0].latest_date : '--' }}</p>
      </div>
    </div>

    <UpdateStatus />

    <div class="search-row">
      <SearchBar @search="onSearch" />
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">股票列表</span>
        <span class="page-info">第 {{ page }} / {{ totalPages }} 页</span>
      </div>
      <div class="panel-body" style="padding: 0;">
        <table class="data-table">
          <thead>
            <tr>
              <th>代码</th>
              <th class="col-number">最新价</th>
              <th class="col-number">成交量</th>
              <th>日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="stock in stocks" :key="stock.symbol" @click="goDetail(stock.symbol)">
              <td class="col-symbol">{{ stock.symbol }}</td>
              <td class="col-number font-mono">{{ stock.close.toFixed(2) }}</td>
              <td class="col-number font-mono">{{ (stock.volume / 10000).toFixed(0) }}<span class="unit">万</span></td>
              <td class="text-muted">{{ stock.latest_date }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="pagination">
      <button class="btn-secondary pagination-btn" :disabled="page <= 1" @click="page--; loadData()">上一页</button>
      <span class="page-indicator">{{ page }} / {{ totalPages }}</span>
      <button class="btn-secondary pagination-btn" :disabled="page >= totalPages" @click="page++; loadData()">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { fetchStocks } from '../api'
import SearchBar from '../components/SearchBar.vue'
import UpdateStatus from '../components/UpdateStatus.vue'

const router = useRouter()
const stocks = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const search = ref('')
const totalPages = computed(() => Math.ceil(total.value / pageSize))

async function loadData() {
  const { data } = await fetchStocks({ search: search.value, page: page.value, page_size: pageSize })
  stocks.value = data.stocks
  total.value = data.total
}

function onSearch(q) {
  search.value = q
  page.value = 1
  loadData()
}

function goDetail(symbol) {
  router.push({ name: 'StockDetail', params: { symbol } })
}

onMounted(loadData)
</script>

<style scoped>
.search-row {
  margin: 12px 0;
}

.page-info {
  font-size: 12px;
  color: var(--st-text-muted);
}

.data-table tbody tr {
  cursor: pointer;
}

.col-symbol {
  color: var(--st-accent) !important;
  font-weight: 600;
}

.unit {
  color: var(--st-text-muted);
  font-size: 11px;
  margin-left: 2px;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 16px;
  padding: 8px 0;
}

.pagination-btn {
  padding: 6px 14px !important;
  font-size: 12px !important;
}

.page-indicator {
  font-size: 13px;
  color: var(--st-text-muted);
  font-family: var(--font-mono);
}
</style>
