const freqMap = { daily: '日线', weekly: '周线', monthly: '月线' }

export function freqLabel(f) {
  return freqMap[f] || f
}

export function statusClass(s) {
  if (s === 'success') return 'success'
  if (s === 'failed') return 'failed'
  if (s === 'running') return 'running'
  return 'pending'
}

export function statusText(s) {
  if (s === 'success') return '成功'
  if (s === 'failed') return '失败'
  if (s === 'running') return '运行中'
  if (s.startsWith && s.startsWith('step_') && s.endsWith('_done')) {
    const m = s.match(/\d+/)
    return m ? `第${m[0]}步完成` : s
  }
  return s
}

export function formatSummary(summary) {
  if (!summary) return '-'
  if (summary.screened_count !== undefined) return `选出 ${summary.screened_count} 只`
  if (summary.total_return !== undefined) {
    const ret = (summary.total_return * 100).toFixed(2)
    const dd = summary.max_drawdown != null ? (summary.max_drawdown * 100).toFixed(2) : null
    return dd ? `收益 ${ret}% / 回撤 ${dd}%` : `收益 ${ret}%`
  }
  return '-'
}
