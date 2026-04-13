import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'StockList', component: () => import('../views/StockList.vue') },
  { path: '/stock/:symbol', name: 'StockDetail', component: () => import('../views/StockDetail.vue') },
  { path: '/strategies', name: 'StrategyList', component: () => import('../views/StrategyList.vue') },
  { path: '/screener', name: 'ScreenerPage', component: () => import('../views/ScreenerPage.vue') },
  { path: '/backtest', name: 'BacktestPage', component: () => import('../views/BacktestPage.vue') },
  { path: '/backtest/result/:id', name: 'BacktestResult', component: () => import('../views/BacktestResult.vue') },
  { path: '/portfolio', name: 'PortfolioList', component: () => import('../views/PortfolioList.vue') },
  { path: '/portfolio/:id', name: 'PortfolioDetail', component: () => import('../views/PortfolioDetail.vue') },
  { path: '/compare', name: 'ComparePage', component: () => import('../views/ComparePage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
