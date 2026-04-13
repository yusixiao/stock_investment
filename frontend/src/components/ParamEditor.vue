<template>
  <div class="param-editor" v-if="items.length">
    <h3>参数设置</h3>
    <div v-for="item in items" :key="item.className + '_' + item.paramKey" class="param-row">
      <label>{{ item.strategyName }} → {{ item.paramKey }}</label>
      <input v-model="item.value" @change="emitOverrides" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'

const props = defineProps({
  pipeline: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:overrides'])

const items = ref([])

watch(() => props.pipeline, (pipeline) => {
  items.value = []
  for (const s of pipeline) {
    for (const [key, conf] of Object.entries(s.params || {})) {
      items.value.push({
        className: s.class_name,
        strategyName: s.name,
        paramKey: key,
        value: conf.default,
      })
    }
  }
}, { immediate: true, deep: true })

function emitOverrides() {
  const overrides = {}
  for (const item of items.value) {
    if (!overrides[item.className]) overrides[item.className] = {}
    let val = item.value
    if (!isNaN(Number(val)) && val !== '') val = Number(val)
    overrides[item.className][item.paramKey] = val
  }
  emit('update:overrides', overrides)
}
</script>

<style scoped>
.param-editor { margin-top: 16px; }
.param-editor h3 { font-size: 14px; color: #606266; margin-bottom: 8px; }
.param-row { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.param-row label { font-size: 13px; min-width: 200px; color: #606266; }
.param-row input { padding: 4px 8px; border: 1px solid #dcdfe6; border-radius: 4px; width: 100px; }
</style>
