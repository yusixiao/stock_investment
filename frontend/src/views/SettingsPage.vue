<template>
  <div class="min-h-screen px-4 pb-6 pt-4 md:px-6">
    <header class="mb-4 rounded-2xl border border-white/8 bg-card/80 p-4 backdrop-blur-sm">
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 class="text-xl font-semibold text-white">系统设置</h1>
          <p class="text-sm text-secondary">配置系统参数与 API 密钥</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button class="btn-secondary" @click="resetSettings" :disabled="!hasDirty">重置</button>
          <button class="btn-primary" @click="saveSettings" :disabled="!hasDirty || isSaving">
            {{ isSaving ? '保存中...' : `保存配置${dirtyCount ? ` (${dirtyCount})` : ''}` }}
          </button>
        </div>
      </div>
    </header>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
      <aside class="rounded-2xl border border-white/8 bg-card/60 p-3 backdrop-blur-sm">
        <p class="mb-2 text-xs uppercase tracking-wide text-muted">配置分类</p>
        <div class="space-y-2">
          <button
            v-for="cat in categories"
            :key="cat.id"
            @click="activeCategory = cat.id"
            class="w-full rounded-lg border px-3 py-2 text-left transition"
            :class="activeCategory === cat.id
              ? 'border-accent bg-cyan/10 text-white'
              : 'border-white/8 bg-elevated/40 text-secondary hover:border-white/16 hover:text-white'"
          >
            <span class="flex items-center justify-between text-sm font-medium">
              {{ cat.title }}
              <span class="text-xs text-muted">{{ cat.count }}</span>
            </span>
            <span class="mt-1 block text-xs text-muted">{{ cat.description }}</span>
          </button>
        </div>
      </aside>

      <section class="space-y-3 rounded-2xl border border-white/8 bg-card/60 p-4 backdrop-blur-sm">
        <div v-for="field in activeFields" :key="field.key" class="rounded-xl border border-white/8 bg-elevated/40 p-4">
          <div class="flex items-center justify-between mb-2">
            <label class="text-sm font-medium text-white">{{ field.label }}</label>
            <span v-if="field.required" class="text-xs text-danger">必填</span>
          </div>
          <p class="text-xs text-muted mb-2">{{ field.description }}</p>
          <input
            v-if="field.type === 'text' || field.type === 'password'"
            :type="field.type"
            v-model="field.value"
            :placeholder="field.placeholder"
            class="input-terminal"
            @input="markDirty(field.key)"
          />
          <select
            v-else-if="field.type === 'select'"
            v-model="field.value"
            class="input-terminal"
            @change="markDirty(field.key)"
          >
            <option v-for="opt in field.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
          <div v-else-if="field.type === 'toggle'" class="flex items-center gap-2">
            <button
              @click="field.value = !field.value; markDirty(field.key)"
              class="w-10 h-5 rounded-full transition-colors relative"
              :class="field.value ? 'bg-cyan' : 'bg-white/20'"
            >
              <span
                class="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
                :class="field.value ? 'translate-x-5' : 'translate-x-0.5'"
              ></span>
            </button>
            <span class="text-sm text-secondary">{{ field.value ? '启用' : '禁用' }}</span>
          </div>
        </div>

        <div v-if="activeFields.length === 0" class="rounded-xl border border-white/8 bg-elevated/40 p-5 text-sm text-secondary">
          当前分类下暂无配置项。
        </div>
      </section>
    </div>

    <!-- Toast -->
    <div v-if="toast" class="fixed bottom-5 right-5 z-50 w-[320px]">
      <div class="rounded-xl border p-3 animate-slide-up" :class="toast.type === 'success' ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-400' : 'border-red-400/30 bg-red-400/10 text-red-400'">
        <p class="text-sm font-medium">{{ toast.type === 'success' ? '操作成功' : '操作失败' }}</p>
        <p class="text-xs mt-0.5 opacity-80">{{ toast.message }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const activeCategory = ref('api')
const isSaving = ref(false)
const toast = ref(null)
const dirtyFields = ref(new Set())

const categories = [
  { id: 'api', title: 'API 配置', description: '大模型及数据源密钥', count: 3 },
  { id: 'data', title: '数据配置', description: '数据存储与更新设置', count: 4 },
  { id: 'backtest', title: '回测配置', description: '回测引擎参数', count: 3 },
  { id: 'system', title: '系统设置', description: '通用系统配置', count: 2 },
]

const fields = ref({
  api: [
    { key: 'OPENAI_API_KEY', label: 'OpenAI API Key', description: '用于 AI 问股功能', type: 'password', value: '', placeholder: 'sk-...', required: true },
    { key: 'OPENAI_BASE_URL', label: 'API Base URL', description: '自定义 API 端点', type: 'text', value: '', placeholder: 'https://api.openai.com/v1' },
    { key: 'EASTMONEY_TIMEOUT', label: '东方财富超时(秒)', description: 'API 请求超时时间', type: 'text', value: '15', placeholder: '15' },
  ],
  data: [
    { key: 'DATA_UPDATE_HOUR', label: '每日更新时间', description: '自动拉取日线数据的时间(小时)', type: 'text', value: '18', placeholder: '18' },
    { key: 'KLINE_SOURCE', label: 'K线数据源', description: '日线数据获取来源', type: 'select', value: 'baostock', options: [{ value: 'baostock', label: 'BaoStock' }, { value: 'eastmoney', label: '东方财富' }] },
    { key: 'AUTO_UPDATE', label: '自动更新', description: '启用每日自动数据更新', type: 'toggle', value: true },
    { key: 'DATA_DIR', label: '数据目录', description: '本地数据存储路径', type: 'text', value: './data', placeholder: './data' },
  ],
  backtest: [
    { key: 'COMMISSION_RATE', label: '佣金费率', description: '买卖佣金费率（万分比）', type: 'text', value: '3', placeholder: '3' },
    { key: 'STAMP_TAX', label: '印花税率', description: '卖出印花税率（千分比）', type: 'text', value: '1', placeholder: '1' },
    { key: 'SLIPPAGE', label: '滑点', description: '模拟滑点比例', type: 'text', value: '0.001', placeholder: '0.001' },
  ],
  system: [
    { key: 'AGENT_MODE', label: 'Agent 模式', description: '启用 AI Agent 问股功能', type: 'toggle', value: false },
    { key: 'LOG_LEVEL', label: '日志级别', description: '系统日志输出级别', type: 'select', value: 'INFO', options: [{ value: 'DEBUG', label: 'DEBUG' }, { value: 'INFO', label: 'INFO' }, { value: 'WARNING', label: 'WARNING' }] },
  ],
})

const activeFields = computed(() => fields.value[activeCategory.value] || [])
const hasDirty = computed(() => dirtyFields.value.size > 0)
const dirtyCount = computed(() => dirtyFields.value.size)

function markDirty(key) {
  dirtyFields.value.add(key)
}

function resetSettings() {
  dirtyFields.value.clear()
  // TODO: reload from backend
}

function saveSettings() {
  isSaving.value = true
  setTimeout(() => {
    isSaving.value = false
    dirtyFields.value.clear()
    toast.value = { type: 'success', message: '配置已保存' }
    setTimeout(() => { toast.value = null }, 3000)
  }, 800)
}
</script>
