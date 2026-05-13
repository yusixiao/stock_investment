import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('../views/HomePage.vue') },
  { path: '/chat', name: 'Chat', component: () => import('../views/ChatPage.vue') },
  { path: '/backtest', name: 'Backtest', component: () => import('../views/BacktestPage.vue') },
  { path: '/portfolio', name: 'Portfolio', component: () => import('../views/PortfolioPage.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/SettingsPage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
