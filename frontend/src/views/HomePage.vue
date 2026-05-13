<template>
  <div class="min-h-screen flex flex-col p-4 md:p-6">
    <header class="flex-shrink-0 mb-4">
      <div class="flex items-center gap-3 max-w-4xl">
        <div class="flex-1 relative">
          <input
            type="text"
            v-model="stockCode"
            @keydown.enter="handleSearch"
            placeholder="输入股票代码，如 600519、000001、00700"
            class="input-terminal w-full"
          />
        </div>
        <button
          @click="handleSearch"
          :disabled="!stockCode.trim()"
          class="btn-primary flex items-center gap-1.5 whitespace-nowrap"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          搜索
        </button>
      </div>
    </header>

    <div class="flex-1 glass-card overflow-hidden relative" style="min-height: 600px;">
      <div v-if="!currentSymbol" class="flex flex-col items-center justify-center h-full text-center">
        <div class="w-16 h-16 mb-4 rounded-2xl bg-white/5 flex items-center justify-center">
          <svg class="w-8 h-8 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 3v18h18M7 16l4-8 4 4 4-6"/>
          </svg>
        </div>
        <h3 class="text-lg font-medium text-white mb-2">股票行情</h3>
        <p class="text-sm text-secondary max-w-sm">
          输入股票代码查看实时 K 线走势图
        </p>
        <div class="flex flex-wrap gap-2 justify-center mt-6 max-w-lg">
          <button
            v-for="item in quickStocks"
            :key="item.code"
            @click="selectStock(item.code)"
            class="chat-quick-btn px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-sm text-secondary hover:text-white hover:border-cyan/40 hover:bg-cyan/5 transition-all"
          >
            {{ item.name }} ({{ item.code }})
          </button>
        </div>
      </div>
      <div v-else ref="chartContainer" class="w-full h-full" style="min-height: 600px;"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'

const stockCode = ref('')
const currentSymbol = ref('')
const chartContainer = ref(null)

const quickStocks = [
  { code: '600519', name: '贵州茅台' },
  { code: '000001', name: '平安银行' },
  { code: '300750', name: '宁德时代' },
  { code: '002594', name: '比亚迪' },
  { code: '600036', name: '招商银行' },
  { code: '000858', name: '五粮液' },
]

function toTradingViewSymbol(code) {
  const c = code.trim()
  if (c.startsWith('6')) return `SSE:${c}`
  if (c.startsWith('0') || c.startsWith('3')) return `SZSE:${c}`
  return c
}

function handleSearch() {
  if (!stockCode.value.trim()) return
  currentSymbol.value = toTradingViewSymbol(stockCode.value)
}

function selectStock(code) {
  stockCode.value = code
  currentSymbol.value = toTradingViewSymbol(code)
}

watch(currentSymbol, async (symbol) => {
  if (!symbol) return
  await nextTick()
  renderChart(symbol)
})

const themeObserver = ref(null)
onMounted(() => {
  themeObserver.value = new MutationObserver(() => {
    if (currentSymbol.value) renderChart(currentSymbol.value)
  })
  themeObserver.value.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})
onUnmounted(() => {
  if (themeObserver.value) themeObserver.value.disconnect()
})

function renderChart(symbol) {
  if (!chartContainer.value) return
  chartContainer.value.innerHTML = ''

  const isLight = document.documentElement.classList.contains('light')
  const script = document.createElement('script')
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
  script.type = 'text/javascript'
  script.async = true
  script.innerHTML = JSON.stringify({
    autosize: true,
    symbol: symbol,
    interval: 'D',
    timezone: 'Asia/Shanghai',
    theme: isLight ? 'light' : 'dark',
    style: '1',
    locale: 'zh_CN',
    allow_symbol_change: true,
    backgroundColor: isLight ? '#ffffff' : '#08080c',
    support_host: 'https://www.tradingview.com',
  })

  const widget = document.createElement('div')
  widget.className = 'tradingview-widget-container'
  widget.style.height = '100%'
  widget.style.width = '100%'

  const widgetInner = document.createElement('div')
  widgetInner.className = 'tradingview-widget-container__widget'
  widgetInner.style.height = '100%'
  widgetInner.style.width = '100%'

  widget.appendChild(widgetInner)
  widget.appendChild(script)
  chartContainer.value.appendChild(widget)
}
</script>
