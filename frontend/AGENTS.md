# AGENTS.md — 前端(React)

> 本文件聚焦**前端**。跨切面铁律(沟通语言、TODO 规范、审视铁律等)见根 `AGENTS.md`。

## 技术栈

- React 19 + TypeScript + Vite 7 + Tailwind v4 + zustand + react-router 7。
- K 线:lightweight-charts;回测曲线:recharts;Markdown:react-markdown。
- **端口**:3001(`vite.config.ts`),代理 `/api → 127.0.0.1:8000`。
- npm name 是 `dsa-web`(早期 daily_stock_analysis 遗留)。
- **从 Vue 迁到 React**(2025 末):旧版备份保留在 `frontend/src_vue_backup/`。

## 组件结构(2026-06-14 重构,零裸露文件)

```
frontend/src/components/
├── stock/      # 首页·个股:KlineChart(lightweight-charts v5)/ StockAutocomplete
├── agent/      # 问股:PhaseProgressCard / dashboard
├── backtest/   # 回测:BacktestAnalysis / Config / History / Result / StrategyRadar / MarketMonitor
├── settings/   # 设置:LLMChannelEditor / NotificationTestPanel 等
├── theme/      # 主题
├── common/     # ~25 通用 UI 组件(共享)
└── layout/     # Shell / SidebarNav / ShellHeader(共享)
```

- 7 页:Home / Backtest / Portfolio / Chat / Settings / Login / NotFound。
- stores(zustand):`agentChatStore / analysisStore / stockPoolStore`。
- api 层:`backtest / portfolio / stocks / agent / auth / history / analysis / systemConfig`。

## K 线图(`KlineChart.tsx`,lightweight-charts v5)

- 默认显示 150 根。
- 价格 MA5/10/20/30/60 可切换、Volume MA5/10、MACD pane。
- **MACD bar = `2 × (DIF - DEA)`**(用户口径,与某些行情软件 1× 不同)。
- 鼠标跟随 Tooltip,左右价格刻度可配。
- K 线显示支持 raw/qfq 切换。

## 回测页三 Tab 结构

策略回测(BacktestAnalysis)/ 策略雷达(StrategyRadar)/ 市场监控(MarketMonitor)。

- 市场下拉含"港股通"(`DisplayMarket = 'A'|'HK'|'US'|'HK_CONNECT'`,`toCacheMarket()` 映射回 HK;`CacheMarket` 保持 3 值,API 契约不动)。

## 历史教训

- **LLMChannelEditor 不兼容后端 SSOT**(2026-05-24):字段命名差太多(`_PROTOCOL` vs `_PROVIDER` / `_MODELS` 列表 vs 单值 / 强写 5 个 litellm 死字段),已隐藏不调用,后续若要做 channel UI 必须**重写**而非沿用。
- **敏感字段不通过 HTTP 下发真实值**(产品级铁律),三态 mask 语义,前端"显示密码"按钮无意义。
- **StrategyGroup 整套已砍**(2026-05-19),前端三层 UI 不要再做。

## 测试

```bash
cd frontend && npm test            # vitest
cd frontend && npm run test:smoke  # Playwright smoke
cd frontend && npx tsc --noEmit    # 类型检查
cd frontend && npm run lint        # ESLint
```
