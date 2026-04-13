<template>
  <div class="search-bar">
    <input
      v-model="query"
      type="text"
      placeholder="搜索股票代码或名称..."
      @input="$emit('search', query)"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
const query = ref('')
defineEmits(['search'])
</script>

<style scoped>
.search-bar input {
  width: 300px;
  padding: 8px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
}
</style>
