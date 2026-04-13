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
