<template>
  <div class="trade-form-overlay" @click.self="$emit('close')">
    <div class="trade-form">
      <h3>录入交易</h3>
      <div class="form-row">
        <label>股票代码</label>
        <input v-model="form.symbol" placeholder="如 600519.SH" class="input" />
      </div>
      <div class="form-row">
        <label>方向</label>
        <select v-model="form.direction" class="input">
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
      </div>
      <div class="form-row">
        <label>价格</label>
        <input v-model.number="form.price" type="number" step="0.01" class="input" />
      </div>
      <div class="form-row">
        <label>数量（股）</label>
        <input v-model.number="form.shares" type="number" step="100" class="input" />
      </div>
      <div class="form-row">
        <label>日期</label>
        <input v-model="form.trade_date" type="date" class="input" />
      </div>
      <div class="form-actions">
        <button class="btn-primary" @click="onSubmit">提交</button>
        <button class="btn-secondary" @click="$emit('close')">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'

const emit = defineEmits(['submit', 'close'])

const today = new Date().toISOString().slice(0, 10)
const form = reactive({
  symbol: '',
  direction: 'buy',
  price: 0,
  shares: 100,
  trade_date: today,
})

function onSubmit() {
  if (!form.symbol || form.price <= 0 || form.shares <= 0) return
  emit('submit', { ...form })
}
</script>

<style scoped>
.trade-form-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.trade-form { background: white; border-radius: 8px; padding: 24px; width: 400px; }
.trade-form h3 { margin: 0 0 16px; }
.form-row { margin-bottom: 12px; }
.form-row label { display: block; font-size: 13px; color: #606266; margin-bottom: 4px; }
.input { width: 100%; padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; box-sizing: border-box; }
.form-actions { display: flex; gap: 8px; margin-top: 16px; }
.btn-primary { background: #409eff; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-secondary { background: #dcdfe6; color: #606266; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
</style>
