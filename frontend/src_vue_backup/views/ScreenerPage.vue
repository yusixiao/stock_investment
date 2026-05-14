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
