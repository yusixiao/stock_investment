<template>
  <div class="pipeline-builder">
    <div class="panel available-panel">
      <div class="panel-header">
        <span class="panel-title">Available Strategies</span>
      </div>
      <div class="panel-body strategy-list">
        <div v-for="s in availableStrategies" :key="s.class_name" class="strategy-item" @click="addToPipeline(s)">
          <span :class="'type-tag type-' + s.strategy_type">{{ typeLabel(s.strategy_type) }}</span>
          <span v-if="s.frequency" :class="'freq-tag freq-' + s.frequency">{{ freqLabel(s.frequency) }}</span>
          <span class="strat-name">{{ s.name }}</span>
        </div>
      </div>
    </div>
    <div class="panel pipeline-panel">
      <div class="panel-header">
        <span class="panel-title">Pipeline{{ pipeline.length ? ` (${pipeline.length})` : '' }}</span>
        <span class="hint" v-if="!pipeline.length">Click strategies to add</span>
      </div>
      <div class="panel-body pipeline-list">
        <template v-for="(item, idx) in pipeline" :key="idx">
          <div class="pipeline-item">
            <span class="step-num">{{ idx + 1 }}</span>
            <span :class="'type-tag type-' + item.strategy_type">{{ typeLabel(item.strategy_type) }}</span>
            <span v-if="item.frequency" :class="'freq-tag freq-' + item.frequency">{{ freqLabel(item.frequency) }}</span>
            <span class="strat-name">{{ item.name }}</span>
            <button v-if="hasParams(item)" class="param-toggle" @click="toggleParams(idx)">{{ expandedIdx === idx ? '−' : '⚙' }}</button>
            <button class="remove-btn" @click="removeFromPipeline(idx)">×</button>
          </div>
          <div v-if="expandedIdx === idx && hasParams(item)" class="param-section">
            <div v-for="(conf, key) in getParamDefs(item)" :key="key" class="param-row">
              <label class="param-label">{{ conf.label || key }}</label>
              <input :type="conf.type === 'float' ? 'number' : 'text'" class="param-input" :value="getParamValue(item, key, conf)" @input="updateParam(idx, key, $event.target.value, conf)" />
            </div>
          </div>
          <div v-if="showJoinToggle(idx)" class="join-toggle" @click="toggleJoinMode(idx)">
            <span :class="'join-badge join-' + getJoinMode(idx)">{{ getJoinMode(idx) === 'correlated' ? '关联 ∩' : '独立 ∪' }}</span>
          </div>
        </template>
      </div>
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
.pipeline-builder { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
.available-panel, .pipeline-panel { min-height: 120px; }
.strategy-list { display: flex; flex-direction: column; gap: 2px; padding: 4px; }
.strategy-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.1s;
}
.strategy-item:hover { border-color: var(--st-accent); background: var(--st-accent-dim); }
.pipeline-list { display: flex; flex-direction: column; gap: 2px; padding: 4px; }
.pipeline-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid var(--st-border);
  background: var(--st-bg-elevated);
}
.step-num { font-size: 10px; font-weight: 700; color: var(--st-accent); min-width: 14px; }
.type-tag {
  display: inline-block;
  padding: 0 5px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.type-screener { background: #1a3a1a; color: #4caf50; }
.type-trader { background: #3a2a1a; color: #ff8c00; }
.type-buy { background: #1a3a2a; color: #10b981; }
.type-sell { background: #3a1a1a; color: #ef4444; }
.freq-tag {
  display: inline-block;
  padding: 0 4px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.freq-daily { background: #1a3a1a; color: #4caf50; }
.freq-weekly { background: #1a2a3a; color: #42a5f5; }
.freq-monthly { background: #3a2a1a; color: #ff8c00; }
.strat-name { font-size: 11px; color: var(--st-text-secondary); }
.hint { font-size: 10px; color: var(--st-text-muted); font-weight: normal; }
.param-toggle {
  margin-left: auto;
  border: 1px solid var(--st-border);
  background: transparent;
  color: var(--st-text-muted);
  font-size: 11px;
  padding: 1px 6px;
  cursor: pointer;
}
.param-toggle:hover { border-color: var(--st-accent); color: var(--st-accent); }
.remove-btn {
  border: none;
  background: none;
  color: var(--st-text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.remove-btn:hover { color: var(--st-danger); }
.param-section {
  background: var(--st-bg-base);
  border: 1px solid var(--st-border-light);
  padding: 6px 8px;
  margin: 0 0 2px 0;
}
.param-row { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
.param-label { font-size: 10px; color: var(--st-text-muted); min-width: 80px; text-transform: uppercase; }
.param-input {
  padding: 2px 6px;
  background: var(--st-bg-surface);
  border: 1px solid var(--st-border);
  color: var(--st-text-primary);
  font-family: var(--font-body);
  font-size: 11px;
  width: 80px;
}
.param-input:focus { outline: none; border-color: var(--st-accent); }
.join-toggle { display: flex; justify-content: center; padding: 2px 0; cursor: pointer; }
.join-badge {
  padding: 1px 8px;
  font-size: 10px;
  font-weight: 700;
  user-select: none;
  letter-spacing: 0.02em;
}
.join-independent { background: var(--st-bg-elevated); color: var(--st-text-muted); border: 1px solid var(--st-border); }
.join-correlated { background: rgba(255, 140, 0, 0.1); color: var(--st-accent); border: 1px solid var(--st-accent); }
</style>
