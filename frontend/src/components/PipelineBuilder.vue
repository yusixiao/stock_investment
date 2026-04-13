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
