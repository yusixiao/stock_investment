### Task 7: 前端 PipelineBuilder 独立/关联切换 UI + BacktestPage 传递 join_modes

**Files:**
- Modify: `frontend/src/components/PipelineBuilder.vue`
- Modify: `frontend/src/views/BacktestPage.vue`

**Prerequisite:** Task 5 complete (backend accepts `join_modes`)

---

- [ ] **Step 1: Update PipelineBuilder.vue — add joinModes prop and toggle UI**

Replace `frontend/src/components/PipelineBuilder.vue` entirely:

```vue
<template>
  <div class="pipeline-builder">
    <div class="available">
      <h3>可用策略</h3>
      <div v-for="s in availableStrategies" :key="s.class_name" class="strategy-card" @click="addToPipeline(s)">
        <span :class="'badge ' + s.strategy_type">{{ s.strategy_type === 'screener' ? '筛选' : '交易' }}</span>
        <span v-if="s.frequency" :class="'freq-badge freq-' + s.frequency">{{ freqLabel(s.frequency) }}</span>
        <span class="name">{{ s.name }}</span>
      </div>
    </div>
    <div class="pipeline">
      <h3>当前管道 <span class="hint" v-if="!pipeline.length">点击左侧策略添加</span></h3>
      <template v-for="(item, idx) in pipeline" :key="idx">
        <div class="pipeline-item">
          <span class="step">{{ idx + 1 }}.</span>
          <span :class="'badge ' + item.strategy_type">{{ item.strategy_type === 'screener' ? '筛选' : '交易' }}</span>
          <span v-if="item.frequency" :class="'freq-badge freq-' + item.frequency">{{ freqLabel(item.frequency) }}</span>
          <span class="name">{{ item.name }}</span>
          <button class="remove-btn" @click="removeFromPipeline(idx)">✕</button>
        </div>
        <div v-if="showJoinToggle(idx)" class="join-toggle" @click="toggleJoinMode(idx)">
          <span :class="'join-badge join-' + getJoinMode(idx)">{{ joinLabel(getJoinMode(idx)) }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  strategies: { type: Array, default: () => [] },
  pipeline: { type: Array, default: () => [] },
  joinModes: { type: Array, default: () => [] },
  mode: { type: String, default: 'backtest' },
})

const emit = defineEmits(['update:pipeline', 'update:joinModes'])

const availableStrategies = computed(() => {
  if (props.mode === 'screener') {
    return props.strategies.filter(s => s.strategy_type === 'screener')
  }
  return props.strategies
})

function screenerItems() {
  return props.pipeline.filter(s => s.strategy_type === 'screener')
}

function screenerIndices() {
  return props.pipeline.map((s, i) => s.strategy_type === 'screener' ? i : -1).filter(i => i >= 0)
}

function showJoinToggle(idx) {
  const indices = screenerIndices()
  const pos = indices.indexOf(idx)
  return pos >= 0 && pos < indices.length - 1
}

function getJoinMode(idx) {
  const indices = screenerIndices()
  const pos = indices.indexOf(idx)
  if (pos < 0) return 'independent'
  return (props.joinModes && props.joinModes[pos]) || 'independent'
}

function toggleJoinMode(idx) {
  const indices = screenerIndices()
  const pos = indices.indexOf(idx)
  if (pos < 0) return
  const modes = [...(props.joinModes || [])]
  while (modes.length < indices.length - 1) modes.push('independent')
  modes[pos] = modes[pos] === 'independent' ? 'correlated' : 'independent'
  emit('update:joinModes', modes)
}

function joinLabel(mode) {
  return mode === 'correlated' ? '关联' : '独立'
}

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

const freqMap = { daily: '日线', weekly: '周线', monthly: '月线' }
function freqLabel(f) { return freqMap[f] || f }

function removeFromPipeline(idx) {
  const item = props.pipeline[idx]
  const newPipeline = props.pipeline.filter((_, i) => i !== idx)
  emit('update:pipeline', newPipeline)
  if (item.strategy_type === 'screener') {
    const oldIndices = screenerIndices()
    const pos = oldIndices.indexOf(idx)
    if (pos >= 0 && props.joinModes && props.joinModes.length > 0) {
      const modes = [...props.joinModes]
      if (pos < modes.length) {
        modes.splice(pos, 1)
      } else if (pos > 0 && pos - 1 < modes.length) {
        modes.splice(pos - 1, 1)
      }
      emit('update:joinModes', modes)
    }
  }
}
</script>

<style scoped>
.pipeline-builder { display: flex; gap: 24px; }
.available, .pipeline { flex: 1; }
.available h3, .pipeline h3 { margin-bottom: 12px; font-size: 14px; color: #606266; }
.hint { color: #c0c4cc; font-weight: normal; font-size: 12px; }
.strategy-card { padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; margin-bottom: 8px; cursor: pointer; display: flex; align-items: center; gap: 8px; }
.strategy-card:hover { border-color: #409eff; background: #ecf5ff; }
.pipeline-item { padding: 8px 12px; border: 1px solid #409eff; border-radius: 4px; margin-bottom: 0; display: flex; align-items: center; gap: 8px; background: #f0f9ff; }
.step { font-weight: bold; color: #409eff; }
.badge { padding: 2px 6px; border-radius: 3px; font-size: 11px; color: white; }
.badge.screener { background: #67c23a; }
.badge.trader { background: #e6a23c; }
.name { font-size: 13px; }
.freq-badge { padding: 2px 6px; border-radius: 3px; font-size: 10px; color: white; }
.freq-daily { background: #909399; }
.freq-weekly { background: #409eff; }
.freq-monthly { background: #e6a23c; }
.remove-btn { margin-left: auto; border: none; background: none; color: #f56c6c; cursor: pointer; font-size: 14px; }
.join-toggle { display: flex; justify-content: center; padding: 4px 0; cursor: pointer; margin-bottom: 0; }
.join-badge { padding: 2px 12px; border-radius: 10px; font-size: 11px; user-select: none; }
.join-independent { background: #e4e7ed; color: #606266; }
.join-correlated { background: #fdf6ec; color: #e6a23c; border: 1px solid #e6a23c; }
</style>
```

- [ ] **Step 2: Update BacktestPage.vue — add joinModes state and pass to API**

In `frontend/src/views/BacktestPage.vue`:

1. Add `joinModes` ref. After `const pipeline = ref([])` (line 75), add:

```javascript
const joinModes = ref([])
```

2. Update PipelineBuilder usage in `<template>` (line 13). Replace:

```html
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" mode="backtest" />
```

With:

```html
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" v-model:joinModes="joinModes" mode="backtest" />
```

3. Update `runBacktestPipeline` to include `join_modes` in the API request body. In the `const body = {` block (lines 125-128), after the `param_overrides` line, add `join_modes`:

```javascript
  const body = {
    pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
    param_overrides: overrides.value,
  }
  if (joinModes.value.length > 0) {
    body.join_modes = joinModes.value
  }
```

- [ ] **Step 3: Verify frontend builds**

Run: `npm run build` (from `frontend/` directory)
Expected: Build succeeds with no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PipelineBuilder.vue frontend/src/views/BacktestPage.vue
git commit -m "feat: add join_modes toggle UI in PipelineBuilder and pass to API"
```

- [ ] **Step 5: Run full backend test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 6: Final commit (if any remaining changes)**

```bash
git add -A
git commit -m "feat: pipeline time correlation — complete implementation"
```
