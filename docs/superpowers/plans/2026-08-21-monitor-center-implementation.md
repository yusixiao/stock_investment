# Monitor Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“盘面监控”占位页实现为两个完全解耦的监控域：策略周期运行监控和手动股票价格监控。

**Architecture:** 新增独立 monitoring service、repository、SQLite 表和 `/api/v1/monitoring` 路由，不复用 Portfolio 账户/策略目标表。策略运行监控只管理策略配置与运行记录；股票价格监控只管理用户输入的市场、股票和阈值；scheduler 在市场刷新成功后分别调度两类任务。

**Tech Stack:** FastAPI、SQLite、DuckDBStore、APScheduler、React 19、TypeScript、Vitest、Testing Library。

**Spec:** `docs/superpowers/specs/2026-08-21-monitor-center-design.md`

## Global Constraints

- 策略运行监控和股票价格监控之间没有外键、导入入口或隐式同步。
- 本阶段不发送邮件、Webhook 或 SMTP 通知，只持久化触发事件。
- 价格判断使用 DuckDBStore 的市场已完成交易日收盘价。
- 调度按 A/HK/US 各自交易日判断，单市场失败不阻断其他市场。
- 监控删除必须是软停用，历史运行记录和价格事件保留。
- 所有业务数据库访问通过 repository/service 层，禁止前端或业务代码直接读取 SQLite 表。
- 长时间策略运行必须后台执行并持久化运行状态。
- 每个生产行为先写失败测试，再写最小实现。

---

### Task 1: Monitoring Persistence Layer

**Files:**
- Modify: `backend/services/db_schema.py`
- Create: `backend/services/monitoring/__init__.py`
- Create: `backend/services/monitoring/models.py`
- Create: `backend/services/monitoring/repository.py`
- Test: `backend/tests/test_monitoring_repository.py`

**Interfaces:**
- `StrategyMonitor` and `StockPriceMonitor` dataclasses expose typed persistence entities.
- `MonitoringRepository.create_strategy_monitor(...)`, `list_strategy_monitors(...)`, `get_strategy_monitor(...)`, `update_strategy_monitor(...)`, `soft_delete_strategy_monitor(...)` manage strategy jobs.
- `MonitoringRepository.create_strategy_run(...)`, `finish_strategy_run(...)`, `list_strategy_runs(...)` manage run history.
- `MonitoringRepository.create_stock_monitor(...)`, `list_stock_monitors(...)`, `get_stock_monitor(...)`, `update_stock_monitor(...)`, `soft_delete_stock_monitor(...)`, `pause_stock_monitor(...)`, `resume_stock_monitor(...)` manage price monitors.
- `MonitoringRepository.claim_price_trigger(...)` atomically transitions `armed -> triggered` and inserts one event; `rearm_price_monitor(...)` transitions `triggered -> armed`.

- [ ] **Step 1: Write failing repository tests**
  - Verify strategy monitor CRUD, soft deletion, and run history persistence.
  - Verify stock monitor CRUD, pause/resume, and independent duplicate symbols with different thresholds.
  - Verify `claim_price_trigger` succeeds once while armed and a second claim does not create a duplicate event.
  - Verify all monitor/event rows survive soft deletion.

- [ ] **Step 2: Run repository tests and verify failure**

  Run: `python -m pytest backend/tests/test_monitoring_repository.py -q`

- [ ] **Step 3: Add idempotent SQLite schema and repository implementation**
  - Add `monitoring_strategy_monitors`, `monitoring_strategy_runs`, `monitoring_stock_monitors`, and `monitoring_stock_events` in `init_portfolio_v1_tables` or a dedicated idempotent schema initializer called from `main.py`.
  - Use status checks and `UPDATE ... WHERE state = 'armed'` for atomic trigger claims.
  - Store strategy params, symbols, and run result as JSON text.

- [ ] **Step 4: Run repository tests and verify green**

  Run: `python -m pytest backend/tests/test_monitoring_repository.py -q`

### Task 2: Stock Price Monitor Evaluation

**Files:**
- Create: `backend/services/monitoring/stock_price_monitor.py`
- Test: `backend/tests/test_stock_price_monitor.py`

**Interfaces:**
- `evaluate_stock_price_monitors(as_of_date: str, markets: set[str] | None = None, connection=None, store=None) -> int` evaluates active monitors and returns event count.
- `_close_for_symbol(market: str, symbol: str, closes: dict[str, float]) -> float | None` follows the existing A/HK/US canonical symbol fallback behavior.

- [ ] **Step 1: Write failing evaluator tests**
  - `close < threshold_price` creates one recorded event and changes state to `triggered`.
  - Re-evaluation while price remains below threshold creates no duplicate event.
  - `close >= threshold_price` rearms a triggered monitor without creating an event.
  - Paused/inactive monitors are ignored.
  - Missing price and failed market query do not change monitor state or block another market.

- [ ] **Step 2: Run evaluator tests and verify failure**

  Run: `python -m pytest backend/tests/test_stock_price_monitor.py -q`

- [ ] **Step 3: Implement evaluator using DuckDBStore and repository claims**
  - Resolve `valuation_date` with `store.previous_trading_date(market, as_of_date)`.
  - Query prices through `store.query_previous_close` or the established DuckDBStore API.
  - Reuse the existing one-shot arm/trigger semantics from `services/portfolio/buy_opportunity.py` without importing Portfolio account or target tables.

- [ ] **Step 4: Run evaluator tests and verify green**

  Run: `python -m pytest backend/tests/test_stock_price_monitor.py -q`

### Task 3: Strategy Monitor Scheduling Contract

**Files:**
- Create: `backend/services/monitoring/strategy_monitor.py`
- Modify: `backend/services/backtest/strategy_loader.py` only if schedule metadata needs a typed frequency contract
- Test: `backend/tests/test_strategy_monitor.py`

**Interfaces:**
- `is_due(frequency: str, market: str, as_of_date: str, store) -> bool` returns whether the date is the first valid trading day for the requested frequency.
- `next_run_date(frequency: str, market: str, after_date: str, store) -> str | None` computes the next trading-day schedule date.
- `run_due_strategy_monitors(as_of_date: str, markets: set[str] | None = None, connection=None, store=None) -> int` claims and runs due strategy monitors, persisting run state.
- Frequency contract is exactly `daily | weekly | monthly | quarterly`; quarterly means the first trading day in January, April, July, or October.

- [ ] **Step 1: Write failing schedule tests**
  - Verify daily, weekly, monthly, and quarterly due-date rules against mocked market trading dates.
  - Verify an already-running monitor cannot be claimed twice.
  - Verify successful run records status/result/task reference and advances `next_run_date`.
  - Verify failed run records error and leaves the previous successful result intact.

- [ ] **Step 2: Run schedule tests and verify failure**

  Run: `python -m pytest backend/tests/test_strategy_monitor.py -q`

- [ ] **Step 3: Implement schedule claiming and strategy execution adapter**
  - Load strategy class/config through the existing Strategy loader.
  - Use a dedicated service boundary for current-date execution; do not fake a historical date range or invoke Python execution from the frontend.
  - Persist `running` before execution and finalize in `success`/`failed` with durable error text.
  - Run long operations through the existing background execution conventions.

- [ ] **Step 4: Run strategy monitor tests and verify green**

  Run: `python -m pytest backend/tests/test_strategy_monitor.py -q`

### Task 4: Monitoring API

**Files:**
- Create: `backend/routers/monitoring.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_monitoring_api.py`

**Interfaces:**
- Register router prefix `/api/v1/monitoring`.
- Strategy endpoints: `GET/POST/PATCH/DELETE /strategy-monitors`, `POST /strategy-monitors/{id}/run`, `GET /strategy-monitors/{id}/runs`.
- Stock endpoints: `GET/POST/PATCH/DELETE /stock-monitors`, `POST /stock-monitors/{id}/pause`, `POST /stock-monitors/{id}/resume`, `GET /stock-monitors/{id}/events`.
- API responses use snake_case server contracts and return typed validation errors for invalid market, symbol, price, frequency, and missing strategy config.

- [ ] **Step 1: Write failing API tests**
  - Verify create/list/update/soft-delete for both monitor types.
  - Verify manual stock monitor creation accepts market/symbol/threshold only and has no strategy/account field.
  - Verify pause/resume and event history endpoints.
  - Verify manual strategy run creates a durable run record.

- [ ] **Step 2: Run API tests and verify failure**

  Run: `python -m pytest backend/tests/test_monitoring_api.py -q`

- [ ] **Step 3: Implement router validation and service calls**
  - Keep strategy and stock endpoint code paths separate.
  - Soft-delete only changes monitor `is_active` and never removes runs/events.
  - Map missing entities to 404 and state conflicts to 409.

- [ ] **Step 4: Run API tests and verify green**

  Run: `python -m pytest backend/tests/test_monitoring_api.py -q`

### Task 5: Scheduler Integration

**Files:**
- Modify: `backend/scheduler.py`
- Test: `backend/tests/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler integration tests**
  - Verify a completed market refresh invokes strategy scheduling and stock price evaluation only for markets whose update/view/cache/result stages succeeded.
  - Verify strategy scheduling failure does not prevent stock evaluation.
  - Verify one market failure does not prevent other markets.

- [ ] **Step 2: Run scheduler tests and verify failure**

  Run: `python -m pytest backend/tests/test_scheduler.py -k "monitor" -q`

- [ ] **Step 3: Add independent callbacks to `_on_market_refresh_complete`**
  - Call `run_due_strategy_monitors` and `evaluate_stock_price_monitors` through separate guarded blocks.
  - Keep the existing Portfolio buy-opportunity flow unchanged; monitoring is a separate domain.
  - Log monitor counts and failures with market/date context.

- [ ] **Step 4: Run scheduler tests and verify green**

  Run: `python -m pytest backend/tests/test_scheduler.py -k "monitor" -q`

### Task 6: Monitor Center Frontend

**Files:**
- Modify: `frontend/src/components/backtest/MarketMonitor.tsx`
- Modify: `frontend/src/api/backtestEngine.ts` or Create: `frontend/src/api/monitoring.ts`
- Create: `frontend/src/api/__tests__/monitoring.test.ts`
- Create/Modify: `frontend/src/components/backtest/__tests__/MarketMonitor.test.tsx`

**Interfaces:**
- `monitoringApi` mirrors the `/api/v1/monitoring` strategy and stock endpoints.
- The component renders two independent sections and never imports Portfolio API/types.

- [ ] **Step 1: Write failing API and component tests**
  - Verify strategy monitor list/create/run/pause/delete calls the monitoring API.
  - Verify stock monitor form requires market, symbol, and positive threshold price.
  - Verify stock monitors render state, latest price, threshold, and pause/resume/delete actions.
  - Verify no UI action or API call imports/uses strategy target or Portfolio account selection.

- [ ] **Step 2: Run frontend tests and verify failure**

  Run: `cd frontend && npm test -- --run src/api/__tests__/monitoring.test.ts src/components/backtest/__tests__/MarketMonitor.test.tsx`

- [ ] **Step 3: Replace in-memory placeholder with API-backed independent sections**
  - Use shared `Button`, `Input`, `Select`, `Card`, `Badge`, `ConfirmDialog` components.
  - Show strategy frequency, next run, last status, and run history summary.
  - Show stock market/symbol/threshold/current price/state/event count.
  - Use explicit loading, empty, error, and confirmation states.

- [ ] **Step 4: Run frontend tests, typecheck, and lint**

  Run: `cd frontend && npm test -- --run src/api/__tests__/monitoring.test.ts src/components/backtest/__tests__/MarketMonitor.test.tsx`, `cd frontend && npx tsc --noEmit`, and `cd frontend && npm run lint`.

### Task 7: Full Regression and Review

**Files:**
- Test only: existing backend and frontend suites

- [ ] **Step 1: Run targeted monitoring tests together**
- [ ] **Step 2: Run backend full suite in the background**

  Run: `nohup python -m pytest backend/tests/ -x -q > logs/monitor-center-backend-full.log 2>&1 &`

- [ ] **Step 3: Run frontend full suite and static checks**

  Run: `cd frontend && npm test`, `cd frontend && npx tsc --noEmit`, and `cd frontend && npm run lint`.

- [ ] **Step 4: Manually verify both independent flows**
  - Create and schedule a strategy monitor without creating a stock monitor.
  - Create a stock monitor manually without selecting a strategy.
  - Confirm strategy runs do not alter stock monitors.
  - Confirm stock trigger state and event history survive page reload.
