<template>
  <div class="search-bar">
    <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
    </svg>
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
.search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--st-bg-card);
  border: 1px solid var(--st-border);
  border-radius: var(--radius-lg);
  padding: 0 14px;
  transition: all 0.2s ease;
}

.search-icon {
  color: var(--st-text-muted);
  flex-shrink: 0;
}

.search-bar input {
  flex: 1;
  padding: 10px 0;
  background: transparent;
  border: none;
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--st-text-primary);
  outline: none;
}

.search-bar input::placeholder {
  color: var(--st-text-muted);
}

.search-bar:focus-within {
  border-color: var(--st-accent);
  box-shadow: 0 0 0 3px var(--st-accent-glow);
}

.search-bar:focus-within .search-icon {
  color: var(--st-accent);
}
</style>
