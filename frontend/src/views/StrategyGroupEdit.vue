<template>
  <div class="group-edit-page">
    <h1>{{ isEdit ? '编辑策略组' : '创建策略组' }}</h1>
    <div class="form-section">
      <label>策略组名称: <input v-model="name" type="text" placeholder="输入策略组名称" /></label>
    </div>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" v-model:joinModes="joinModes" mode="backtest" />
    <div class="actions">
      <button class="btn-primary" @click="save" :disabled="!name || !pipeline.length">{{ isEdit ? '保存修改' : '创建' }}</button>
      <button class="btn-secondary" @click="$router.back()">取消</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchStrategies, fetchGroup, createGroup, updateGroup } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'

const route = useRoute()
const router = useRouter()
const groupId = computed(() => route.params.groupId)
const isEdit = computed(() => !!groupId.value)

const strategies = ref([])
const name = ref('')
const pipeline = ref([])
const joinModes = ref([])

async function save() {
  const pipelineData = pipeline.value.map(s => ({
    filepath: s.filepath,
    class_name: s.class_name,
    frequency: s.frequency || 'daily',
    params: s.params || {},
  }))
  if (isEdit.value) {
    await updateGroup(groupId.value, { name: name.value, pipeline: pipelineData, join_modes: joinModes.value })
    router.push(`/backtest/group/${groupId.value}`)
  } else {
    const { data } = await createGroup({ name: name.value, pipeline: pipelineData, join_modes: joinModes.value })
    router.push(`/backtest/group/${data.group_id}`)
  }
}

onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
  if (isEdit.value) {
    const { data: group } = await fetchGroup(groupId.value)
    name.value = group.name
    pipeline.value = group.pipeline
    joinModes.value = group.join_modes || []
  }
})
</script>

<style scoped>
.group-edit-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.form-section { margin-bottom: 16px; }
.form-section label { font-size: 14px; display: flex; align-items: center; gap: 8px; }
.form-section input { padding: 6px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; width: 300px; }
.actions { margin-top: 20px; display: flex; gap: 12px; }
.btn-primary { padding: 8px 16px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-primary:disabled { background: #c0c4cc; cursor: not-allowed; }
.btn-secondary { padding: 8px 16px; background: white; color: #606266; border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 14px; }
</style>
