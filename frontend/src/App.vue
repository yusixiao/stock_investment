<template>
  <div id="app">
    <nav class="top-nav">
      <router-link to="/">行情</router-link>
      <router-link to="/strategies">策略</router-link>
      <router-link to="/debug">策略调试</router-link>
      <router-link to="/backtest">回测</router-link>
      <router-link to="/portfolio">持仓</router-link>
      <router-link to="/compare">对比</router-link>
    </nav>
    <router-view />
  </div>
</template>

<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.top-nav { display: flex; gap: 0; background: #409eff; padding: 0; }
.top-nav a { color: white; text-decoration: none; padding: 12px 20px; font-size: 14px; transition: background 0.2s; }
.top-nav a:hover { background: rgba(255,255,255,0.15); }
.top-nav a.router-link-active { background: rgba(255,255,255,0.25); font-weight: bold; }
</style>
