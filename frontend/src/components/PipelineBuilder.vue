<template>
  <div class="pipeline-builder">
    <div class="available">
      <h3>可用策略</h3>
      <div v-for="s in availableStrategies" :key="s.class_name" class="strategy-card" @click="addToPipeline(s)">
        <span :class="'badge ' + s.strategy_type">{{ typeLabel(s.strategy_type) }}</span>
        <span v-if="s.frequency" :class="'freq-badge freq-' + s.frequency">{{ freqLabel(s.frequency) }}</span>
        <span class="name">{{ s.name }}</span>
      </div>
    </div>
    <div class="pipeline">
      <h3>当前管道 <span class="hint" v-if="!pipeline.length">点击左侧策略添加</span></h3>
      <template v-for="(item, idx) in pipeline" :key="idx">
        <div class="pipeline-item">
          <span class="step">{{ idx + 1 }}.</span>
          <span :class="'badge ' + item.strategy_type">{{ typeLabel(item.strategy_type) }}</span>
          <span v-if="item.frequency" :class="'freq-badge freq-' + item.frequency">{{ freqLabel(item.frequency) }}</span>
          <span class="name">{{ item.name }}</span>
          <button v-if="hasParams(item)" class="param-toggle" @click="toggleParams(idx)">{{ expandedIdx === idx ? '收起' : '参数' }}</button>
          <button class="remove-btn" @click="removeFromPipeline(idx)">✕</button>
        </div>
        <div v-if="expandedIdx === idx && hasParams(item)" class="param-section">
          <div v-for="(conf, key) in getParamDefs(item)" :key="key" class="param-row">
            <label>{{ conf.label || key }}:</label>
            <input :type="conf.type === 'float' ? 'number' : 'text'" :value="getParamValue(item, key, conf)" @input="updateParam(idx, key, $event.target.value, conf)" />
          </div>
        </div>
        <div v-if="showJoinToggle(idx)" class="join-toggle" @click="toggleJoinMode(idx)">
          <span :class="'join-badge join-' + getJoinMode(idx)">{{ getJoinMode(idx) === 'correlated' ? '关联' : '独立' }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { freqLabel } from '../utils/format'

const props = defineProps({
  strategies: { type: Array, default: () => [] },
  pipeline: { type: Array, default: () => [] },
  joinModes: { type: Array, default: () => [] },
  mode: { type: String, default: 'backtest' },
})

const emit = defineEmits(['update:pipeline', 'update:joinModes'])

const expandedIdx = ref(null)

function toggleParams(idx) {
  expandedIdx.value = expandedIdx.value === idx ? null : idx
}

function hasParams(item) {
  const defs = getParamDefs(item)
  return Object.keys(defs).length > 0
}

function getParamDefs(item) {
  const params = item.params || {}
  const defs = {}
  for (const [key, val] of Object.entries(params)) {
    if (val && typeof val === 'object' && 'default' in val) {
      defs[key] = val
    } else {
      defs[key] = { default: val, label: key, type: typeof val === 'number' ? 'int' : 'str' }
    }
  }
  return defs
}

function getParamValue(item, key, conf) {
  const params = item.params || {}
  const val = params[key]
  if (val && typeof val === 'object' && 'default' in val) return val.default
  return val !== undefined ? val : conf.default
}

function updateParam(idx, key, rawValue, conf) {
  const newPipeline = [...props.pipeline]
  const item = { ...newPipeline[idx], params: { ...newPipeline[idx].params } }
  let val = rawValue
  if (conf.type === 'int') val = parseInt(rawValue) || 0
  else if (conf.type === 'float') val = parseFloat(rawValue) || 0
  const existing = item.params[key]
  if (existing && typeof existing === 'object' && 'default' in existing) {
    item.params[key] = { ...existing, default: val }
  } else {
    item.params[key] = val
  }
  newPipeline[idx] = item
  emit('update:pipeline', newPipeline)
}

const availableStrategies = computed(() => {
  if (props.mode === 'screener') {
    return props.strategies.filter(s => s.strategy_type === 'screener')
  }
  return props.strategies
})

function typeLabel(t) { const map = { screener: '筛选', trader: '交易', buy: '买入', sell: '卖出' }; return map[t] || t }

function addToPipeline(strategy) {
  const hasTrader = props.pipeline.some(s => s.strategy_type === 'trader')
  if (strategy.strategy_type === 'trader' && hasTrader) return
  if (strategy.strategy_type === 'buy' && props.pipeline.some(s => s.strategy_type === 'buy')) return
  if (strategy.strategy_type === 'sell' && props.pipeline.some(s => s.strategy_type === 'sell')) return
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

function screenerIndices() {
  return props.pipeline
    .map((s, i) => s.strategy_type === 'screener' ? i : -1)
    .filter(i => i >= 0)
}

function showJoinToggle(idx) {
  const si = screenerIndices()
  if (props.pipeline[idx]?.strategy_type !== 'screener') return false
  const pos = si.indexOf(idx)
  return pos >= 0 && pos < si.length - 1
}

function getJoinMode(idx) {
  const si = screenerIndices()
  const pos = si.indexOf(idx)
  return (props.joinModes[pos]) || 'independent'
}

function toggleJoinMode(idx) {
  const si = screenerIndices()
  const pos = si.indexOf(idx)
  if (pos < 0) return
  const newModes = [...props.joinModes]
  while (newModes.length <= pos) newModes.push('independent')
  newModes[pos] = newModes[pos] === 'correlated' ? 'independent' : 'correlated'
  emit('update:joinModes', newModes)
}

function removeFromPipeline(idx) {
  const item = props.pipeline[idx]
  if (item.strategy_type === 'screener') {
    const si = screenerIndices()
    const pos = si.indexOf(idx)
    if (pos >= 0 && props.joinModes.length > 0) {
      const newModes = [...props.joinModes]
      if (pos < newModes.length) {
        newModes.splice(pos, 1)
      } else if (pos > 0 && pos - 1 < newModes.length) {
        newModes.splice(pos - 1, 1)
      }
      emit('update:joinModes', newModes)
    }
  }
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
.badge.buy { background: #10b981; color: white; }
.badge.sell { background: #ef4444; color: white; }
.name { font-size: 13px; }
.freq-badge { padding: 2px 6px; border-radius: 3px; font-size: 10px; color: white; }
.freq-daily { background: #909399; }
.freq-weekly { background: #409eff; }
.freq-monthly { background: #e6a23c; }
.remove-btn { margin-left: auto; border: none; background: none; color: #f56c6c; cursor: pointer; font-size: 14px; }
.param-toggle { border: 1px solid #dcdfe6; background: #f5f7fa; color: #606266; border-radius: 3px; font-size: 11px; padding: 2px 8px; cursor: pointer; }
.param-toggle:hover { border-color: #409eff; color: #409eff; }
.param-section { background: #fafafa; border: 1px solid #ebeef5; border-radius: 4px; padding: 8px 12px; margin: -4px 0 8px 0; }
.param-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.param-row label { font-size: 12px; color: #606266; min-width: 100px; }
.param-row input { padding: 3px 8px; border: 1px solid #dcdfe6; border-radius: 4px; width: 80px; font-size: 12px; }
.join-toggle { display: flex; justify-content: center; margin: -4px 0 8px; cursor: pointer; }
.join-badge { padding: 2px 10px; border-radius: 10px; font-size: 11px; user-select: none; }
.join-independent { background: #e4e7ed; color: #909399; }
.join-correlated { background: #fdf6ec; color: #e6a23c; border: 1px solid #e6a23c; }
</style>
