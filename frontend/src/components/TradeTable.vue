<template>
  <div class="trade-table-wrapper">
    <h3>交易明细 ({{ trades.length }} 笔)</h3>
    <table class="trade-table">
      <thead>
        <tr>
          <th>日期</th>
          <th>股票</th>
          <th>方向</th>
          <th>价格</th>
          <th>数量</th>
          <th>金额</th>
          <th>佣金</th>
          <th>印花税</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(t, i) in trades" :key="i">
          <td>{{ t.date }}</td>
          <td>{{ t.symbol }}</td>
          <td :class="t.direction === 'buy' ? 'buy' : 'sell'">{{ t.direction === 'buy' ? '买入' : '卖出' }}</td>
          <td>{{ t.price?.toFixed(2) }}</td>
          <td>{{ t.shares }}</td>
          <td>{{ t.amount?.toFixed(0) }}</td>
          <td>{{ t.commission?.toFixed(2) }}</td>
          <td>{{ t.tax?.toFixed(2) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({ trades: { type: Array, default: () => [] } })
</script>

<style scoped>
.trade-table-wrapper { margin-top: 16px; }
.trade-table-wrapper h3 { font-size: 14px; color: #606266; }
.trade-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.trade-table th, .trade-table td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #ebeef5; }
.buy { color: #ef5350; }
.sell { color: #26a69a; }
</style>
