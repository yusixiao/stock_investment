# Task 6 报告

## 删除与保留依据

- 删除 `backend/services/agent/` runtime 实现及 `backend/tests/agent/` 专属测试。仓库 retained runtime 无 agent import；定性分析 spike 脚本同样只依赖已删除实现，因此一并删除。
- 删除 `backend/services/system_config/` runtime 实现及 `backend/tests/system_config/` 专属测试。其唯一生产消费者是已删除 agent；无 retained runtime import。
- 删除 `backend/services/portfolio/` runtime 实现及 portfolio/buy-opportunity 专属测试。monitoring、backtest、market refresh 继续直接使用 `config.PORTFOLIO_DB` 和各自 repository/schema，不依赖 portfolio service。
- 从 `backend/services/db_schema.py` 移除 `init_chat_tables`、`init_portfolio_v1_tables` 及其 portfolio 状态归档 helper。没有新增 DROP 或 destructive migration；`data/portfolio.db` 旧表未修改。
- 从 `backend/config.py` 移除仅供 agent/qualitative cache 使用的 `CACHE_DIR`、`QUALITATIVE_DIR` 常量及目录初始化。保留 `PORTFOLIO_DB`、`LOG_DIR`、策略目录和 scheduler 常量，因为 retained backtest/monitoring/refresh 仍使用。
- 删除 frontend agent API、旧 analysis API、agent dashboard/store、system config API/types/hooks、settings 组件及专属测试、chat-only helpers 和 markdown 转换工具。保留回测使用的 `buildPositionSummary`、`buildMergedTradeRows`、monitoring API、backtest API 及 retained common `api/error.ts`。
- 删除 frontend 未被 retained module 使用的 `motion`、`react-markdown`、`remark-gfm`、`remove-markdown` 及对应类型依赖，并更新 lockfile。保留 `xlsx`、图表、路由、主题和回测所需依赖。
- import inventory 最终未发现 `services.portfolio`、`services.agent`、`services.system_config`、`portfolioApi`、`agentApi`、`systemConfigApi` 或已删除 frontend hook/helper 的 retained import。

## 数据库校验

- 清理前目标旧表集合（`portfolio_*`、`chat_*`、auth-related）为空。
- 清理后 `data/portfolio.db` 现有表集合为：`backtest_tasks`、`monitoring_stock_events`、`monitoring_stock_monitors`、`monitoring_strategy_monitors`、`monitoring_strategy_runs`、`sqlite_sequence`、`stock_exclusions`；清理过程未执行数据库写操作。
- backend runtime bootstrap 与 monitoring 测试均通过，且未恢复任何 portfolio/chat DDL。

## 测试命令与结果

- `rtk npm run build`（依赖移除前）：失败，已有回测测试类型错误，涉及 `DataCacheModal.test.tsx`、`useMonitorActions.test.ts`、`BacktestConfig.tsx`、`MarketMonitor.tsx`、`useMonitorActions.ts`；非本任务删除引入。
- `python -m pytest backend/tests/ -x -q`：1094 passed，1 个既有未处理线程异常 warning（测试线程使用临时 SQLite 时缺少 `backtest_tasks`）。
- `rtk npm test`：29 test files passed，244 tests passed。
- `rtk npx tsc --noEmit`：通过，无 TypeScript 错误。
- `rtk npm run lint`：通过。
- `rtk npm run test:smoke`：失败。仓库没有 Playwright 配置/独立 smoke tests，Playwright 错误读取 `import.meta.env`、解析 `App.css`，并报告 Vitest runner 未初始化；属于现有 smoke 配置问题。
- `python -m py_compile backend/services/db_schema.py backend/config.py backend/tests/test_monitoring_api.py backend/tests/test_runtime_bootstrap.py`：通过。
- repository-wide import inventory：无目标模块残余 import。

## 未解决 concerns

- frontend `npm run build` 的既有回测测试类型错误仍未处理；本任务未修改回测实现或测试契约。
- frontend smoke 流程当前不可执行，需要后续补充 Playwright 配置、真实 smoke spec 和正确的 Vite test environment 注入。
- backend 全量测试虽通过，但保留了已有 SQLite 临时库线程 warning，建议后续单独修复测试隔离/线程收尾。

## 提交

- 实现提交：`086dff2` (`refactor: prune retired platform modules`)

## 最终审查修复波次

- `BacktestConfig` 仅在 payload 含 `metrics` 时调用回测结果 mapper，避免把 `ScanRadarPayload` 当作回测结果，未改变后端 payload schema。
- 修正 `MarketMonitor` 和 `useMonitorActions` 的 discriminated union narrowing；补齐缓存、策略和股票监控测试 fixture 的接口字段。
- 删除无 retained import 的 `frontend/src/api/history.ts`；保留 `buildPositionSummary` 与 `buildMergedTradeRows`。
- 新增 `frontend/playwright.config.ts` 和 `frontend/tests/smoke/app.spec.ts`，Playwright 只扫描专用 smoke 目录并自动启动 Vite 3001；Vite Vitest include 限定为 `src/**/*.test|spec.*`，避免反向扫描 smoke spec。

## 最终审查验证

- `cd frontend && npm run build`：通过；Vite bundle 构建成功，仅有 chunk 大小提示。
- `cd frontend && npm test`：29 个 test files、244 tests 全部通过。
- `cd frontend && npx tsc --noEmit`：通过，无 TypeScript 错误。
- `cd frontend && npm run lint`：通过。
- `cd frontend && npm run test:smoke`：1 个真实 smoke test 通过；验证 `/` 进入 `/backtest` 且“回测平台”和“策略回测”可见。
- 为本机 smoke 环境安装了 Playwright Chromium；测试不依赖后端真实数据。

## 最终 concerns

- Vite build 有现有 bundle 超过 500 kB 的性能提示，未改变本次产品范围。
- Playwright webServer 输出既有 PostCSS `from` 警告，但 smoke 已通过。
