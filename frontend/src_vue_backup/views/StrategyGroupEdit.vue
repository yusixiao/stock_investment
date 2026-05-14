<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">{{ isEdit ? '编辑策略组' : '创建策略组' }}</h1>
    </div>
    <div class="card form-card">
      <div class="form-group">
        <label class="form-label">策略组名称</label>
        <input v-model="name" type="text" class="form-input" placeholder="输入策略组名称" />
      </div>
    </div>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" v-model:joinModes="joinModes" mode="backtest" />
    <div class="form-actions">
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
    name: s.name || s.class_name,
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
.form-card {
  margin-bottom: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-actions {
  margin-top: 16px;
  display: flex;
  gap: 10px;
}

.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>
