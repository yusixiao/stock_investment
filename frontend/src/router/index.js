import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'StockList', component: () => import('../views/StockList.vue') },
  { path: '/stock/:symbol', name: 'StockDetail', component: () => import('../views/StockDetail.vue') },
  { path: '/strategies', name: 'StrategyList', component: () => import('../views/StrategyList.vue') },
  { path: '/debug', name: 'StrategyDebug', component: () => import('../views/StrategyDebug.vue') },
  { path: '/backtest', name: 'StrategyGroupList', component: () => import('../views/StrategyGroupList.vue') },
  { path: '/backtest/group/create', name: 'StrategyGroupCreate', component: () => import('../views/StrategyGroupEdit.vue') },
  { path: '/backtest/group/:groupId/edit', name: 'StrategyGroupEditExisting', component: () => import('../views/StrategyGroupEdit.vue') },
  { path: '/backtest/group/:groupId', name: 'StrategyGroupDetail', component: () => import('../views/StrategyGroupDetail.vue') },
  { path: '/backtest/group/:groupId/run/:runId', name: 'RunDetail', component: () => import('../views/RunDetail.vue') },
  { path: '/backtest/result/:id', name: 'BacktestResult', component: () => import('../views/BacktestResult.vue') },
  { path: '/portfolio', name: 'PortfolioList', component: () => import('../views/PortfolioList.vue') },
  { path: '/portfolio/:id', name: 'PortfolioDetail', component: () => import('../views/PortfolioDetail.vue') },
  { path: '/compare', name: 'ComparePage', component: () => import('../views/ComparePage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
