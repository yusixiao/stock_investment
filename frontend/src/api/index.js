import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export function fetchStocks(params = {}) {
  return api.get('/stocks', { params })
}

export function fetchKline(symbol, params = {}) {
  return api.get(`/stocks/${symbol}/kline`, { params })
}

export function fetchIndicators(symbol, params = {}) {
  return api.get(`/stocks/${symbol}/indicators`, { params })
}

export function triggerUpdate(date) {
  return api.post('/data/update', date ? { date } : {})
}

export function fetchUpdateStatus() {
  return api.get('/data/update/status')
}

export function fetchUpdateLogs(limit = 20) {
  return api.get('/data/update/logs', { params: { limit } })
}

export function fetchStrategies() {
  return api.get('/backtest/strategies')
}

export function runBacktest(body) {
  return api.post('/backtest/run', body)
}

export function fetchBacktestStatus(taskId) {
  return api.get(`/backtest/status/${taskId}`)
}

export function fetchBacktestResult(taskId) {
  return api.get(`/backtest/result/${taskId}`)
}

export function runScreener(body) {
  return api.post('/screener/run', body)
}

export function fetchScreenerResult() {
  return api.get('/screener/result')
}

export function fetchBacktestTasks(showDeleted = false) {
  return api.get('/backtest/tasks', { params: showDeleted ? { show_deleted: true } : {} })
}

export function deleteBacktestTask(taskId) {
  return api.delete(`/backtest/tasks/${taskId}`)
}

export function createPortfolio(body) {
  return api.post('/portfolio/', body)
}

export function listPortfolios() {
  return api.get('/portfolio/')
}

export function getPortfolio(id) {
  return api.get(`/portfolio/${id}`)
}

export function deletePortfolio(id) {
  return api.delete(`/portfolio/${id}`)
}

export function addTrade(portfolioId, body) {
  return api.post(`/portfolio/${portfolioId}/trades`, body)
}

export function getTrades(portfolioId) {
  return api.get(`/portfolio/${portfolioId}/trades`)
}

export function getHoldings(portfolioId) {
  return api.get(`/portfolio/${portfolioId}/holdings`)
}

export function getSnapshots(portfolioId) {
  return api.get(`/portfolio/${portfolioId}/snapshots`)
}

export function importFromBacktest(taskId, body) {
  return api.post(`/portfolio/import/${taskId}`, body)
}

export default api
