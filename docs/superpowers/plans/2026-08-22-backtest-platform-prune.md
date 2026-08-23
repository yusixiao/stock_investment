# 回测平台功能裁剪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有综合投资系统裁剪为只提供回测、雷达、历史、盘面监控、监控调度和市场数据能力的回测平台。

**Architecture:** 保留现有回测执行、DuckDB、MarketBundle、RefreshRunner 和 monitoring module；从运行时入口移除 portfolio、agent、system config、auth 和首页数据面。将 monitoring schema 从 portfolio schema 中独立出来，旧 SQLite 表保留但不再初始化或访问。

**Tech Stack:** FastAPI、SQLite、DuckDB、APScheduler、React 19、TypeScript、React Router 7、Vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-08-22-backtest-platform-prune-design.md`

## Global Constraints

- 只保留策略回测、策略雷达、回测历史、盘面监控和策略监控调度。
- `BacktestEngine.run()` 与 `run_scan()` 的结果 schema 不变。
- DuckDB 是唯一业务数据入口，业务数据物理路径仍为 `data/market/`。
- 保留 A/HK/US 市场更新、DuckDB、MarketBundle、缓存和刷新状态。
- 现有 `data/portfolio.db` 中的 portfolio/chat/auth 旧表不删除。
- 不新增兼容路由，不恢复首页/个股详情数据面。
- 代码、测试、用户可见文本使用中文；代码标识符和日志保持英文。

---

### Task 1: 拆分 Monitoring Schema Bootstrap

**Files:**
- Modify: `backend/services/db_schema.py`
- Modify: `backend/services/monitoring/repository.py`
- Modify: `backend/services/monitoring/strategy_monitor.py`
- Modify: `backend/services/monitoring/stock_price_monitor.py`
- Test: `backend/tests/test_monitoring_repository.py`
- Test: `backend/tests/test_strategy_monitor.py`
- Test: `backend/tests/test_stock_price_monitor.py`
- Create: `backend/tests/test_runtime_schema.py`

**Interfaces:**
- Produces `init_monitoring_tables(conn: sqlite3.Connection) -> None` in `services.db_schema`.
- `init_monitoring_tables` creates or migrates only `monitoring_strategy_monitors`, `monitoring_strategy_runs`, `monitoring_stock_monitors`, and `monitoring_stock_events`, including existing CHECK constraints and indexes.
- Monitoring modules call `init_monitoring_tables`, never `init_portfolio_v1_tables`.
- `init_backtest_tables` remains responsible only for `backtest_tasks` and `stock_exclusions`.

- [ ] **Step 1: Write the failing schema tests**

Add tests to `backend/tests/test_runtime_schema.py` using a fresh `tmp_path` SQLite database:

```python
def test_runtime_schema_creates_backtest_refresh_and_monitoring_tables_without_product_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "runtime.db")
    init_backtest_tables(conn)
    init_market_refresh_tables(conn)
    init_monitoring_tables(conn)

    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"backtest_tasks", "stock_exclusions", "market_refreshes", "market_refresh_versions"} <= tables
    assert {
        "monitoring_strategy_monitors",
        "monitoring_strategy_runs",
        "monitoring_stock_monitors",
        "monitoring_stock_events",
    } <= tables
    assert "portfolio_accounts" not in tables
    assert "chat_sessions" not in tables
    conn.close()


def test_runtime_schema_preserves_old_product_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute("CREATE TABLE portfolio_accounts (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY)")
    conn.commit()

    init_backtest_tables(conn)
    init_market_refresh_tables(conn)
    init_monitoring_tables(conn)

    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"portfolio_accounts", "chat_sessions"} <= tables
    conn.close()
```

- [ ] **Step 2: Run the focused schema tests and verify failure**

Run: `python -m pytest backend/tests/test_runtime_schema.py -q`

Expected: FAIL because `init_monitoring_tables` does not exist and the current monitoring DDL is coupled to portfolio bootstrap.

- [ ] **Step 3: Extract monitoring DDL and migration logic**

Move the four monitoring table definitions, `_ensure_monitoring_constraints`, monitoring indexes, and only the migration code required by those four tables into `init_monitoring_tables`. Do not move portfolio table definitions. Keep the existing migration data-preserving behavior.

Replace monitoring callers that currently execute:

```python
from services.db_schema import init_portfolio_v1_tables
init_portfolio_v1_tables(connection)
```

with:

```python
from services.db_schema import init_monitoring_tables
init_monitoring_tables(connection)
```

- [ ] **Step 4: Run the focused schema and monitoring tests**

Run: `python -m pytest backend/tests/test_runtime_schema.py backend/tests/test_monitoring_repository.py backend/tests/test_strategy_monitor.py backend/tests/test_stock_price_monitor.py -q`

Expected: PASS; monitoring behavior and legacy-table preservation remain covered.

- [ ] **Step 5: Run the complete backend test suite**

Run: `python -m pytest backend/tests/ -x -q`

Expected: PASS, or only failures caused by tests that still import removed product modules; record those files for Task 5 rather than weakening runtime schema behavior.

### Task 2: Replace Application Bootstrap and Remove Product Scheduler Work

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/scheduler.py`
- Modify: `backend/services/db_schema.py` if a small `init_runtime_tables` helper improves startup locality
- Modify: `backend/tests/test_scheduler.py`
- Modify: `backend/tests/test_scheduler_market_retry.py`
- Test: `backend/tests/test_runtime_bootstrap.py`

**Interfaces:**
- Application lifespan initializes backtest, market refresh, monitoring, DuckDB, stock index, and cache only.
- `_on_market_refresh_complete(record)` retains monitoring strategy scheduling and stock-price evaluation.
- `_on_market_refresh_complete(record)` no longer imports or calls portfolio snapshot or buy-opportunity code.
- Scheduler still starts the market refresh jobs and retry jobs.

- [ ] **Step 1: Add a failing scheduler regression test**

In `backend/tests/test_scheduler.py`, patch the refresh record with successful market stages and patch the monitoring functions. Assert both monitoring functions are called and portfolio functions are not imported or called:

```python
def test_refresh_completion_keeps_monitoring_and_drops_portfolio_work(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "services.monitoring.strategy_monitor.run_due_strategy_monitors",
        lambda *args, **kwargs: calls.append("strategy") or 1,
    )
    monkeypatch.setattr(
        "services.monitoring.stock_price_monitor.evaluate_stock_price_monitors",
        lambda *args, **kwargs: calls.append("stock") or 1,
    )

    record = make_completed_refresh_record(markets={"A"})
    _on_market_refresh_complete(record)

    assert calls == ["strategy", "stock"]
```

Use the existing test record factory or add a local dataclass fixture with `status`, `source`, and `market_states` matching `RefreshRecord`.

- [ ] **Step 2: Run the focused scheduler test and verify failure**

Run: `python -m pytest backend/tests/test_scheduler.py -k refresh_completion_keeps_monitoring_and_drops_portfolio_work -q`

Expected: FAIL because the current callback still invokes `_evaluate_buy_opportunities_after_refresh` and imports portfolio code.

- [ ] **Step 3: Remove portfolio work from the scheduler**

Delete `_snapshot_job`, `_evaluate_buy_opportunities_after_refresh`, its scheduler registration, and all portfolio imports. Keep `_on_market_refresh_complete` market-success filtering and monitoring calls unchanged except for removing the buy-opportunity branch.

Update `main.py` imports and lifespan so it no longer imports `services.portfolio.db.init_db`. Initialize only the retained runtime tables before DuckDB and cache startup.

- [ ] **Step 4: Run scheduler and startup tests**

Run: `python -m pytest backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py backend/tests/test_runtime_bootstrap.py -q`

Expected: PASS with monitoring callbacks retained and no portfolio bootstrap.

### Task 3: Remove Backend Product Routes and Unused Data-Facing Routes

**Files:**
- Modify: `backend/main.py`
- Delete: `backend/routers/portfolio_v1.py`
- Delete: `backend/routers/agent.py`
- Delete: `backend/routers/system_config.py`
- Delete: `backend/routers/auth_stub.py`
- Delete: `backend/routers/stock.py`
- Delete: `backend/routers/stock_search.py`
- Delete: `backend/routers/market_kline.py`
- Delete: `backend/routers/screener.py`
- Modify: `backend/tests` files importing removed routers
- Test: `backend/tests/test_route_surface.py`

**Interfaces:**
- The FastAPI application registers only retained backtest, cache, monitoring, market update, metadata, HK-connect, and health routes.
- No route is added as a compatibility alias for removed product features.
- Internal `DuckDBStore`, MarketBundle and stock index imports remain available to retained modules.

- [ ] **Step 1: Add route-surface assertions**

Create `backend/tests/test_route_surface.py`:

```python
def test_backtest_platform_route_surface():
    paths = {route.path for route in app.routes}
    assert "/api/backtest/run" in paths
    assert "/api/backtest/scan-radar" in paths
    assert "/api/backtest/cache/status" in paths
    assert "/api/v1/monitoring/strategy-monitors" in paths
    assert "/api/market-update/trigger" in paths
    assert "/api/v1/portfolio/accounts" not in paths
    assert "/api/v1/agent/chat/stream" not in paths
    assert "/api/v1/system/config" not in paths
    assert "/api/v1/auth/status" not in paths
    assert "/api/stocks/{symbol}/kline" not in paths
```

- [ ] **Step 2: Run the route test and verify failure**

Run: `python -m pytest backend/tests/test_route_surface.py -q`

Expected: FAIL because `main.py` still registers the removed routers.

- [ ] **Step 3: Remove router registration and files**

Delete imports and `app.include_router(...)` calls for the removed routers. Delete the router files only after repository-wide import search shows no retained module imports them. Remove tests that exclusively test deleted product behavior; preserve any shared fixtures needed by backtest/monitoring tests.

- [ ] **Step 4: Run route, import, and backend tests**

Run: `python -m pytest backend/tests/test_route_surface.py backend/tests/test_backtest_api.py backend/tests/test_monitoring_api.py -q`

Expected: PASS. Then run `python -m pytest backend/tests/ -x -q` and resolve only stale imports caused by the deliberate product deletion.

### Task 4: Simplify Frontend Entry and Workbench Shell

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Shell.tsx`
- Modify: `frontend/src/components/layout/SidebarNav.tsx` or replace it with a backtest-only header module
- Modify: `frontend/src/pages/BacktestPage.tsx`
- Delete: `frontend/src/pages/HomePage.tsx`
- Delete: `frontend/src/pages/ChatPage.tsx`
- Delete: `frontend/src/pages/PortfolioPage.tsx`
- Delete: `frontend/src/pages/SettingsPage.tsx`
- Delete: `frontend/src/pages/LoginPage.tsx`
- Delete: `frontend/src/pages/NotFoundPage.tsx`
- Delete: `frontend/src/contexts/AuthContext.tsx`
- Delete: `frontend/src/api/auth.ts`
- Delete: `frontend/src/stores/agentChatStore.ts`
- Test: `frontend/src/pages/__tests__/BacktestPage.test.tsx`
- Test: create/update `frontend/src/App.test.tsx`

**Interfaces:**
- `App` renders a backtest-only route tree without `AuthProvider`.
- `/` and unknown paths render `<Navigate to="/backtest" replace />`.
- `Shell` presents a compact “回测平台” header with four existing workspace tabs and theme toggle; it does not render a single-item TreeView/sidebar drawer.
- `DataCacheStatusBar` remains globally mounted.

- [ ] **Step 1: Add failing route and shell tests**

Add tests asserting root redirect and the absence of removed navigation labels:

```tsx
it('redirects the root route to the backtest workbench', async () => {
  renderAppAt('/');
  expect(await screen.findByRole('tab', { name: '策略回测' })).toBeInTheDocument();
});

it('does not render product navigation that was removed', async () => {
  renderAppAt('/backtest');
  expect(screen.queryByText('首页')).not.toBeInTheDocument();
  expect(screen.queryByText('持仓')).not.toBeInTheDocument();
  expect(screen.queryByText('问股')).not.toBeInTheDocument();
  expect(screen.queryByText('设置')).not.toBeInTheDocument();
  expect(screen.queryByText('退出')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused frontend tests and verify failure**

Run: `cd frontend && npm test -- src/App.test.tsx src/pages/__tests__/BacktestPage.test.tsx`

Expected: FAIL because `App` still requires authentication and `Shell` still renders the old navigation.

- [ ] **Step 3: Implement the backtest-only route tree and header**

Remove authentication branches and imports from `App.tsx`. Keep only the `/backtest` route inside the shell and redirect `/`/unknown paths to it. Replace `SidebarNav` usage with the compact header specified in the design; keep the four tab controls in `BacktestPage` as the primary workspace navigation and keep `DataCacheStatusBar`.

- [ ] **Step 4: Remove page-only files and update tests**

Delete the removed pages, auth context/API, agent store, and their tests after verifying no retained import remains. Do not delete monitoring, backtest, cache, strategy, or shared theme modules.

- [ ] **Step 5: Run focused frontend validation**

Run: `cd frontend && npm test -- src/App.test.tsx src/pages/__tests__/BacktestPage.test.tsx src/components/backtest`

Expected: PASS with all four backtest tabs and data cache behavior intact.

### Task 5: Remove Portfolio Coupling From Backtest and Prune Frontend APIs

**Files:**
- Modify: `frontend/src/components/backtest/BacktestResult.tsx`
- Modify: `frontend/src/components/backtest/BacktestHistory.tsx`
- Modify: `frontend/src/components/backtest/__tests__/BacktestResult.test.tsx`
- Modify: `frontend/src/components/backtest/__tests__/BacktestHistory.test.tsx`
- Delete: `frontend/src/api/portfolio.ts`
- Delete: `frontend/src/types/portfolio.ts`
- Delete: `frontend/src/api/__tests__/portfolio.test.ts`
- Delete: `frontend/src/components/backtest/useStrategyAccountBinding.ts`
- Delete: `frontend/src/components/backtest/__tests__/useStrategyAccountBinding.test.ts`
- Delete: `frontend/src/api/agent.ts`, `frontend/src/api/systemConfig.ts`, and their types/hooks after retained-import search

**Interfaces:**
- Backtest result rendering accepts only backtest result data and task metadata.
- Backtest history supports inspect, delete, and monitor-history behavior without account lookup/binding.
- No retained backtest module imports `portfolioApi`, `portfolio` types, `agentApi`, or `systemConfigApi`.

- [ ] **Step 1: Add failing regression assertions**

In the existing result/history tests, assert that rendering a successful result does not call account APIs and that no bind-account action is rendered:

```tsx
it('does not offer account binding for a completed backtest', async () => {
  render(<BacktestResult task={completedTask} />);
  expect(screen.queryByRole('button', { name: /绑定账户/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /解除绑定/ })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `cd frontend && npm test -- src/components/backtest/__tests__/BacktestResult.test.tsx src/components/backtest/__tests__/BacktestHistory.test.tsx`

Expected: FAIL or expose existing account-binding expectations, proving the coupling still exists.

- [ ] **Step 3: Remove account binding from backtest views**

Delete account lookup, account selection, binding, unbinding, and related success/error state. Preserve backtest metrics, trades, equity curve, result details, task deletion, monitor history, and exports.

- [ ] **Step 4: Delete unused frontend API/type modules**

Run a repository-wide import search first. Delete `portfolio.ts`, `types/portfolio.ts`, `api/__tests__/portfolio.test.ts`, `useStrategyAccountBinding.ts`, and its test after Task 5 removes their imports. Keep `buildPositionSummary.ts` and `buildMergedTradeRows.ts` because `BacktestResult.tsx` still uses them to render backtest trade/position summaries; they are not portfolio-management modules. Delete `backtest.ts`, `analysis.ts`, and `history.ts` only after the search confirms no retained backtest or monitoring module imports them.

- [ ] **Step 5: Run focused tests and type checking**

Run: `cd frontend && npm test -- src/components/backtest && npx tsc --noEmit`

Expected: PASS with no portfolio/account imports in the retained backtest surface.

### Task 6: Remove Agent/System/Portfolio Implementations and Complete Dependency Cleanup

**Files:**
- Delete: `backend/services/portfolio/` runtime modules after import search
- Delete: `backend/services/agent/` runtime modules and `backend/tests/agent/`
- Delete: `backend/services/system_config/` runtime modules and `backend/tests/system_config/`
- Modify: `backend/services/db_schema.py` to remove runtime portfolio/chat schema functions while retaining all existing database tables untouched
- Modify: `backend/config.py` to remove only constants made unreachable by deleted modules
- Delete: `frontend/src/api/agent.ts`
- Delete: `frontend/src/api/systemConfig.ts`
- Delete: `frontend/src/types/systemConfig.ts`
- Delete: `frontend/src/hooks/useSystemConfig.ts`
- Delete: `frontend/src/utils/systemConfigI18n.ts`
- Delete: `frontend/src/locales/settingsHelp.ts`
- Delete: `frontend/src/components/settings/`
- Delete: `frontend/src/utils/chatExport.ts`, `frontend/src/utils/chatFollowUp.ts`, and `frontend/src/utils/chatScroll.ts`
- Delete: `frontend/src/hooks/useTaskStream.ts` and its test after confirming it has no retained backtest/monitoring import
- Modify: `frontend/package.json` to remove dependencies no retained module uses
- Modify: backend tests and frontend tests that exclusively exercise deleted modules
- Test: repository-wide import checks and full test suites

**Interfaces:**
- No retained runtime module imports `services.portfolio`, `services.agent`, `services.system_config`, or auth implementation modules.
- Existing old tables remain untouched in `data/portfolio.db`; no destructive migration is added.
- Market data adapters, updaters, DuckDB store, backtest strategies, monitoring, and scheduler imports remain valid.

- [ ] **Step 1: Run import inventory before deletion**

Run:

```bash
rtk grep -n "services\.portfolio\|services\.agent\|services\.system_config\|portfolioApi\|agentApi\|systemConfigApi" backend frontend/src
```

Expected: only files listed in Tasks 1-5 and product-only tests remain.

- [ ] **Step 2: Delete product implementations and stale tests**

Delete only modules with no retained imports. If a shared utility is used by backtest or monitoring, move or retain it rather than deleting by directory name. Do not delete market-data adapters or strategy code merely because their symbols mention stock data.

- [ ] **Step 3: Remove unused frontend dependencies only after build evidence**

Run `cd frontend && npm run build` before editing `package.json`. Remove a dependency only when the repository-wide import search confirms it is unused; run `npm install`/lockfile update only for actual dependency removals.

- [ ] **Step 4: Run full backend validation**

Run: `python -m pytest backend/tests/ -x -q`

Expected: PASS with route surface, schema preservation, refresh/monitor scheduling, backtest, radar, cache, and task tests covered.

- [ ] **Step 5: Run full frontend validation**

Run:

```bash
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
cd frontend && npm run test:smoke
```

Expected: all retained backtest/monitoring tests pass; no removed product route or UI is reachable.

- [ ] **Step 6: Verify runtime route and data preservation**

Start the backend and frontend in the normal development configuration. Verify `/` opens the backtest workbench, cache loading works for A/HK/US, all four tabs render, monitor creation/listing/manual run works, and a refresh completion schedules monitors. Before and after startup, compare the set of old `portfolio_*`, `chat_*`, and auth-related tables in `data/portfolio.db`; assert none were dropped.

## Execution Order

Tasks are intentionally ordered to preserve monitoring first:

1. Task 1 creates the independent monitoring schema seam.
2. Task 2 removes portfolio work from startup and refresh callbacks.
3. Task 3 removes backend route surface.
4. Task 4 makes the frontend backtest-only entry point.
5. Task 5 removes the remaining portfolio coupling inside retained views.
6. Task 6 deletes unreachable implementations and validates the complete platform.

Do not delete product modules before the import inventory in Task 6 confirms that retained backtest and monitoring code no longer depends on them.
