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

export function triggerUpdate() {
  return api.post('/data/update')
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

export function fetchBacktestTasks() {
  return api.get('/backtest/tasks')
}

export default api
