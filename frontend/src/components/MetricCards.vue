<template>
  <div class="metric-cards">
    <div class="card" v-for="m in displayMetrics" :key="m.key">
      <div class="label">{{ m.label }}</div>
      <div class="value" :class="m.colorClass">{{ m.display }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ metrics: { type: Object, default: () => ({}) } })

const displayMetrics = computed(() => {
  const m = props.metrics
  if (!m) return []
  return [
    { key: 'total_return', label: '总收益率', display: pct(m.total_return), colorClass: m.total_return >= 0 ? 'up' : 'down' },
    { key: 'annualized_return', label: '年化收益率', display: pct(m.annualized_return), colorClass: m.annualized_return >= 0 ? 'up' : 'down' },
    { key: 'max_drawdown', label: '最大回撤', display: pct(m.max_drawdown), colorClass: 'down' },
    { key: 'sharpe_ratio', label: '夏普比率', display: num(m.sharpe_ratio), colorClass: '' },
    { key: 'win_rate', label: '胜率', display: pct(m.win_rate), colorClass: '' },
    { key: 'profit_loss_ratio', label: '盈亏比', display: num(m.profit_loss_ratio), colorClass: '' },
    { key: 'trade_count', label: '交易次数', display: m.trade_count ?? '-', colorClass: '' },
  ]
})

function pct(v) { return v != null ? (v * 100).toFixed(2) + '%' : '-' }
function num(v) { return v != null ? Number(v).toFixed(2) : '-' }
</script>

<style scoped>
.metric-cards { display: flex; flex-wrap: wrap; gap: 12px; }
.card { padding: 12px 16px; border: 1px solid #ebeef5; border-radius: 6px; min-width: 140px; text-align: center; }
.label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.value { font-size: 20px; font-weight: bold; }
.up { color: #ef5350; }
.down { color: #26a69a; }
</style>
