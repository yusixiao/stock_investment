<template>
  <div class="stock-list-page">
    <h1>A 股列表</h1>
    <SearchBar @search="onSearch" />
    <table class="stock-table">
      <thead>
        <tr>
          <th>代码</th>
          <th>最新价</th>
          <th>成交量</th>
          <th>最新日期</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="stock in stocks" :key="stock.symbol" @click="goDetail(stock.symbol)">
          <td>{{ stock.symbol }}</td>
          <td>{{ stock.close.toFixed(2) }}</td>
          <td>{{ (stock.volume / 10000).toFixed(0) }}万</td>
          <td>{{ stock.latest_date }}</td>
        </tr>
      </tbody>
    </table>
    <div class="pagination">
      <button :disabled="page <= 1" @click="page--; loadData()">上一页</button>
      <span>第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
      <button :disabled="page >= totalPages" @click="page++; loadData()">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { fetchStocks } from '../api'
import SearchBar from '../components/SearchBar.vue'

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
.stock-list-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.stock-table { width: 100%; border-collapse: collapse; margin-top: 16px; }
.stock-table th, .stock-table td { padding: 10px; text-align: left; border-bottom: 1px solid #ebeef5; }
.stock-table tbody tr { cursor: pointer; }
.stock-table tbody tr:hover { background: #f5f7fa; }
.pagination { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
</style>
