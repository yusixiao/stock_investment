<template>
  <div class="h-screen flex flex-col w-full p-4 md:p-6">
    <header class="mb-6 flex-shrink-0">
      <h1 class="text-2xl font-bold text-white mb-2 flex items-center gap-2">
        <svg class="w-6 h-6 text-cyan" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
        </svg>
        问股
      </h1>
      <p class="text-secondary text-sm">向 AI 询问个股分析，获取基于策略的交易建议与实时决策报告。</p>
    </header>

    <div class="flex-1 flex flex-col glass-card overflow-hidden min-h-0 relative z-10">
      <div class="flex-1 overflow-y-auto p-4 md:p-6 space-y-6" ref="messagesContainer">
        <div v-if="messages.length === 0 && !loading" class="h-full flex flex-col items-center justify-center text-center">
          <div class="w-16 h-16 mb-4 rounded-2xl bg-white/5 chat-empty-icon flex items-center justify-center">
            <svg class="w-8 h-8 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          <h3 class="text-lg font-medium text-white mb-2">开始问股</h3>
          <p class="text-sm text-secondary max-w-sm mb-6">
            输入「分析 600519」或「茅台现在能买吗」，AI 将调用实时数据工具为您生成决策报告。
          </p>
          <div class="flex flex-wrap gap-2 justify-center max-w-lg">
            <button
              v-for="(q, i) in quickQuestions"
              :key="i"
            @click="handleQuickQuestion(q)"
            class="chat-quick-btn px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-sm text-secondary hover:text-white hover:border-cyan/40 hover:bg-cyan/5 transition-all"
            >
              {{ q.label }}
            </button>
          </div>
        </div>

        <template v-else>
          <div v-for="msg in messages" :key="msg.id" class="flex gap-4" :class="msg.role === 'user' ? 'flex-row-reverse' : ''">
            <div
              class="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold"
              :class="msg.role === 'user' ? 'bg-cyan text-black' : 'bg-white/10 text-white chat-avatar-ai'"
            >
              {{ msg.role === 'user' ? 'U' : 'AI' }}
            </div>
            <div
              class="max-w-[80%] rounded-2xl px-5 py-3.5"
              :class="msg.role === 'user'
                ? 'bg-cyan/10 text-white border border-cyan/20 rounded-tr-sm chat-bubble-user'
                : 'bg-white/5 text-secondary border border-white/10 rounded-tl-sm chat-bubble-assistant'"
            >
              <div v-if="msg.role === 'assistant' && msg.strategy" class="mb-2">
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan/10 border border-cyan/20 text-xs text-cyan">
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                  </svg>
                  {{ msg.strategy }}
                </span>
              </div>
              <div v-if="msg.role === 'assistant'" class="prose prose-invert prose-sm max-w-none" v-html="msg.content"></div>
              <template v-else>
                <p v-for="(line, idx) in msg.content.split('\n')" :key="idx" class="mb-1 last:mb-0 leading-relaxed">{{ line || '\u00A0' }}</p>
              </template>
            </div>
          </div>
        </template>

        <div v-if="loading" class="flex gap-4">
          <div class="w-8 h-8 rounded-full bg-white/10 text-white chat-avatar-ai flex items-center justify-center flex-shrink-0 text-xs font-bold">AI</div>
          <div class="bg-white/5 border border-white/10 rounded-2xl rounded-tl-sm px-5 py-4 min-w-[200px] chat-bubble-assistant">
            <div class="flex items-center gap-2.5 text-sm text-secondary">
              <div class="relative w-4 h-4 flex-shrink-0">
                <div class="absolute inset-0 rounded-full border-2 border-cyan/20"></div>
                <div class="absolute inset-0 rounded-full border-2 border-cyan border-t-transparent animate-spin"></div>
              </div>
              <span>AI 正在思考...</span>
            </div>
          </div>
        </div>
      </div>

      <div class="p-4 md:p-6 border-t border-white/5 bg-black/20 chat-input-area relative z-20">
        <div class="mb-3 flex flex-wrap gap-x-5 gap-y-2 items-start">
          <span class="text-xs text-muted font-medium uppercase tracking-wider flex-shrink-0 mt-1">策略</span>
          <label
            v-for="s in strategies"
            :key="s.id"
            class="flex items-center gap-1.5 cursor-pointer group mt-0.5"
          >
            <input
              type="radio"
              name="strategy"
              :value="s.id"
              v-model="selectedStrategy"
              class="w-3.5 h-3.5 accent-cyan"
            />
            <span
              class="transition-colors text-sm"
              :class="selectedStrategy === s.id ? 'text-white font-medium' : 'text-secondary group-hover:text-white'"
            >
              {{ s.name }}
            </span>
          </label>
        </div>

        <div class="flex gap-3 items-end">
          <textarea
            v-model="input"
            @keydown="handleKeyDown"
            placeholder="例如：分析 600519 / 茅台现在适合买入吗？ (Enter 发送, Shift+Enter 换行)"
            :disabled="loading"
            rows="1"
            class="input-terminal flex-1 min-h-[44px] max-h-[200px] py-2.5 resize-none"
            @input="autoResize"
          ></textarea>
          <button
            @click="handleSend()"
            :disabled="!input.trim() || loading"
            class="btn-primary h-[44px] px-6 flex-shrink-0 flex items-center justify-center gap-2"
          >
            <svg v-if="loading" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
            </svg>
            发送
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const messages = ref([])
const input = ref('')
const loading = ref(false)
const selectedStrategy = ref('bull_trend')
const messagesContainer = ref(null)

const strategies = [
  { id: 'bull_trend', name: '趋势分析' },
  { id: 'chan_theory', name: '缠论' },
  { id: 'wave_theory', name: '波浪理论' },
  { id: 'box_oscillation', name: '箱体震荡' },
  { id: 'emotion_cycle', name: '情绪周期' },
]

const quickQuestions = [
  { label: '用缠论分析茅台', strategy: 'chan_theory' },
  { label: '波浪理论看宁德时代', strategy: 'wave_theory' },
  { label: '分析比亚迪趋势', strategy: 'bull_trend' },
  { label: '箱体震荡策略看中芯国际', strategy: 'box_oscillation' },
  { label: '用情绪周期分析东方财富', strategy: 'emotion_cycle' },
]

function handleQuickQuestion(q) {
  selectedStrategy.value = q.strategy
  handleSend(q.label)
}

async function handleSend(overrideMessage) {
  const msgText = overrideMessage || input.value.trim()
  if (!msgText || loading.value) return

  const strategyName = strategies.find(s => s.id === selectedStrategy.value)?.name || ''

  messages.value.push({
    id: Date.now().toString(),
    role: 'user',
    content: msgText,
  })
  input.value = ''
  loading.value = true

  await nextTick()
  scrollToBottom()

  // Simulate AI response (backend not implemented yet)
  setTimeout(() => {
    messages.value.push({
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: `<p>这是一个模拟回复。后续接入 AI 后将返回基于<strong>${strategyName}</strong>策略的分析结果。</p><p>当前功能尚在开发中，请稍候。</p>`,
      strategy: strategyName,
    })
    loading.value = false
    nextTick(() => scrollToBottom())
  }, 1500)
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function autoResize(e) {
  const t = e.target
  t.style.height = 'auto'
  t.style.height = `${Math.min(t.scrollHeight, 200)}px`
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}
</script>

<style>
:root.light .chat-bubble-assistant {
  background: rgba(0, 0, 0, 0.03) !important;
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: var(--text-primary) !important;
}

:root.light .chat-bubble-user {
  background: rgba(0, 153, 204, 0.08) !important;
  border-color: rgba(0, 153, 204, 0.2) !important;
}

:root.light .chat-input-area {
  background: rgba(0, 0, 0, 0.02) !important;
  border-color: rgba(0, 0, 0, 0.06) !important;
}

:root.light .chat-empty-icon {
  background: rgba(0, 0, 0, 0.04) !important;
}

:root.light .chat-avatar-ai {
  background: rgba(0, 0, 0, 0.08) !important;
  color: var(--text-primary) !important;
}

:root.light .chat-quick-btn {
  background: rgba(0, 0, 0, 0.03) !important;
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: var(--text-secondary) !important;
}

:root.light .chat-quick-btn:hover {
  background: rgba(0, 153, 204, 0.06) !important;
  border-color: rgba(0, 153, 204, 0.3) !important;
  color: var(--text-primary) !important;
}
</style>
