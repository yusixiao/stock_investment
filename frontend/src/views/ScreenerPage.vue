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
      <table class="result-table" v-if="result.count">
        <thead>
          <tr><th>股票代码</th><th>匹配次数</th><th>匹配日期</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in result.screened_symbols" :key="item.symbol">
            <td>
              <span class="symbol-link" @click="$router.push('/stock/' + item.symbol)">{{ item.symbol }}</span>
            </td>
            <td>{{ item.match_dates.length }}</td>
            <td>
              <span v-for="(d, i) in item.match_dates" :key="d" class="date-tag">{{ d }}<span v-if="i < item.match_dates.length - 1">、</span></span>
            </td>
          </tr>
        </tbody>
      </table>
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
.result-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.result-table th { text-align: left; padding: 10px 8px; border-bottom: 2px solid #ebeef5; color: #909399; font-weight: normal; }
.result-table td { padding: 10px 8px; border-bottom: 1px solid #ebeef5; }
.symbol-link { color: #409eff; cursor: pointer; font-weight: bold; }
.symbol-link:hover { text-decoration: underline; }
.date-tag { font-size: 12px; color: #606266; }
</style>
