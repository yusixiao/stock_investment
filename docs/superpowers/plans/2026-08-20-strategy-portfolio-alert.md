# 策略持仓与买入提醒 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在统一持仓页面中支持策略账户、目标持仓、买入范围校验和基于上一交易日收盘价的买入机会事件，同时把执行中的回测任务关联账户并永久置顶。

**Architecture:** 回测任务保持不可变，只增加 `execution_status` 与 `execution_account_id` 元数据。用户绑定任务时，Portfolio 模块从 `backtest_tasks.result` 读取并物化自己的策略目标历史；真实交易仍是账户持仓的唯一事实来源。提醒评估模块读取目标与实际持仓，满足条件时调用 `BuyOpportunitySink`，不实现邮件渠道。

**Tech Stack:** Python 3.13, FastAPI, SQLite, DuckDBStore, APScheduler, React 19, TypeScript, Zustand/Vitest。

**Spec:** `docs/superpowers/specs/2026-08-20-strategy-portfolio-alert-design.md`

## Global Constraints

- 回测任务只作为不可变策略事实来源，不回写账户持仓或提醒状态。
- 业务数据只能经 `DuckDBStore` 访问，禁止业务代码直接读取 parquet。
- 账户绑定策略后只限制买入股票范围，不限制价格和数量；卖出不受限制。
- 一个账户最多绑定一个任务，一个任务最多绑定一个账户。
- 当前任务只生成买入机会事件，不实现邮件、Webhook、SMTP 或卖出提醒。
- 修改共享 `data/portfolio.db` schema 必须使用幂等迁移，并兼顾回测和问股表。

---

### Task 1: 回测任务执行关联

**Files:**
- Modify: `backend/services/db_schema.py`
- Modify: `backend/services/backtest/task_manager.py`
- Modify: `backend/routers/backtest.py`
- Modify: `frontend/src/api/backtestEngine.ts`
- Modify: `frontend/src/components/backtest/BacktestHistory.tsx`
- Test: `backend/tests/test_backtest_task_manager.py`
- Test: `backend/tests/test_backtest_api.py`
- Test: `frontend/src/components/backtest/__tests__/BacktestHistory.test.tsx`

**Interfaces:**
- Add `execution_status: Literal["inactive", "active"]` and `execution_account_id: int | None` to task list/detail responses.
- Add `TaskManager.set_execution_account(task_id: str, account_id: int) -> dict` and `TaskManager.clear_execution_account(task_id: str) -> dict`.
- Keep task `status` unchanged; `execution_status` is independent metadata.
- Portfolio account binding calls these manager methods; no new public backtest execution endpoint is required in this phase.

- [ ] **Step 1: Write failing backend schema and manager tests**
  - Verify migration adds nullable `execution_account_id` and `execution_status` defaulting to `inactive`.
  - Verify setting a task/account association makes the task active.
  - Verify the same account or task cannot have two active associations.
  - Verify `list_tasks()` orders active tasks before inactive tasks, retaining `created_at DESC` inside each group.

- [ ] **Step 2: Run focused backend tests and verify they fail**

```bash
python -m pytest backend/tests/test_backtest_task_manager.py backend/tests/test_backtest_api.py -x -q
```

- [ ] **Step 3: Implement idempotent columns, manager methods, and response fields**
  - Add migration guarded by `_column_exists`.
  - Update `get_result()` and `list_tasks()` without changing existing result JSON.
  - Expose execution metadata through existing task list/detail responses; account binding remains the only mutation entry point.

- [ ] **Step 4: Implement frontend task typing and stable ordering**
  - Add execution fields to `TaskListItem`.
  - In `BacktestHistory.sortedTasks`, compare active state before return sort so active tasks remain first for default, ascending, and descending modes.
  - Render an “执行中” badge without changing existing task actions.

- [ ] **Step 5: Run focused tests**

```bash
python -m pytest backend/tests/test_backtest_task_manager.py backend/tests/test_backtest_api.py -q
cd frontend && npm test -- src/components/backtest/__tests__/BacktestHistory.test.tsx
```

---

### Task 2: Portfolio v1 domain schema and account binding

**Files:**
- Create: `backend/services/portfolio/models.py`
- Create: `backend/services/portfolio/repository.py`
- Modify: `backend/services/portfolio/db.py`
- Modify: `backend/services/db_schema.py`
- Create: `backend/services/portfolio/account_service.py`
- Create: `backend/routers/portfolio_v1.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_portfolio_account_service.py`
- Test: `backend/tests/test_portfolio_v1_api.py`

**Interfaces:**
- `create_account(name: str, market: str, base_currency: str, strategy_task_id: str | None) -> Account`
- `bind_strategy(account_id: int, task_id: str) -> Account`
- `unbind_strategy(account_id: int) -> Account`
- `get_account(account_id: int) -> Account`
- `list_accounts(include_inactive: bool = False) -> list[Account]`

- [ ] **Step 1: Add failing tests for account lifecycle and one-to-one binding**
  - New accounts default to unbound.
  - Binding fails if the account has current stock holdings.
  - Binding fails when the task is not successful, already active, or already linked to another account.
  - Unbinding preserves trades and clears execution metadata on the task.

- [ ] **Step 2: Implement new account tables and repository methods**
  - Use new `/api/v1/portfolio` tables rather than the old `portfolios` contract.
  - Keep `data/portfolio.db` shared DDL idempotent.
  - Store the nullable strategy binding and timestamps.

- [ ] **Step 3: Implement account service and v1 routes**
  - Route account bind/unbind operations through the service.
  - On bind, call the target materializer from Task 3 in the same application transaction.
  - On unbind, archive target/reminder state and clear task execution metadata.

- [ ] **Step 4: Run focused tests**

```bash
python -m pytest backend/tests/test_portfolio_account_service.py backend/tests/test_portfolio_v1_api.py -q
```

---

### Task 3: Materialize strategy target history

**Files:**
- Create: `backend/services/portfolio/strategy_targets.py`
- Modify: `backend/services/portfolio/repository.py`
- Modify: `backend/routers/portfolio_v1.py`
- Test: `backend/tests/test_strategy_targets.py`

**Interfaces:**
- `materialize_targets(account_id: int, task_id: str) -> int`
- `get_current_targets(account_id: int, as_of_date: str) -> list[StrategyTarget]`
- `get_target_history(account_id: int) -> list[StrategyTargetRevision]`
- `is_buy_allowed(account_id: int, symbol: str, as_of_date: str) -> bool`

- [ ] **Step 1: Write failing target tests using task `2baab97c` fixture data**
  - Materialize the five `2026-06-02` targets with their strategy quantities and reference prices.
  - For an `as_of_date` in August 2026, select `2026-06-02` because it is the latest effective target not later than the evaluation date.
  - Ignore target dates after `as_of_date`.
  - Preserve target history and represent removed symbols with `target_quantity=0`.
  - Allow buys only for current targets with positive target quantity.

- [ ] **Step 2: Implement a read-only task-result adapter**
  - Read `backtest_tasks.result` through the task repository.
  - Parse the existing result contract without changing the backtest task schema or result JSON.
  - Produce an account-owned target history during binding; later reads use the materialized tables only.
  - Return a domain error when the selected result cannot provide a target recommendation instead of silently deriving an unsafe target.

- [ ] **Step 3: Implement current-target selection and buy-range validation**
  - Select `max(effective_date)` where `effective_date <= as_of_date`.
  - Use the latest target revision per symbol.
  - Keep target quantity, reference price, status, and source task metadata.

- [ ] **Step 4: Run focused tests**

```bash
python -m pytest backend/tests/test_strategy_targets.py -q
```

---

### Task 4: Real trades, holdings overlay, and buy opportunity evaluator

**Files:**
- Create: `backend/services/portfolio/holdings_service.py`
- Create: `backend/services/portfolio/buy_opportunity.py`
- Modify: `backend/services/portfolio/repository.py`
- Modify: `backend/scheduler.py`
- Test: `backend/tests/test_portfolio_holdings_service.py`
- Test: `backend/tests/test_buy_opportunity.py`
- Test: `backend/tests/test_scheduler.py`

**Interfaces:**
- `record_trade(account_id: int, symbol: str, side: Literal["buy", "sell"], quantity: int, price: float, trade_date: str, fee: float = 0, tax: float = 0) -> Trade`
- `get_holdings(account_id: int, as_of_date: str | None = None) -> list[Holding]`
- `evaluate_buy_opportunities(as_of_date: str, sink: BuyOpportunitySink) -> int`
- `BuyOpportunitySink.emit(alert: BuyOpportunityAlert) -> None`

- [ ] **Step 1: Write failing trade and evaluator tests**
  - Unbound accounts accept any buy.
  - Bound accounts reject non-target buys, but accept target buys at any price and quantity.
  - Over-target holdings have `remaining_quantity=0` and no alert.
  - Target zero with remaining actual holdings stays visible but produces no buy alert.
  - Fully sold holdings disappear from active holdings while realized P&L remains in history.
  - A previous-day close below the reference price emits an alert only when remaining quantity is positive.
  - Continuous below-threshold closes do not emit duplicates; a close at/above the threshold rearms the symbol.
  - A newly materialized target already below its reference price emits once without requiring a prior above-threshold close.

- [ ] **Step 2: Implement trade validation and holdings projection**
  - Keep transaction records as the source of actual shares/cost/P&L.
  - Apply target-range validation only to buy transactions on bound accounts.
  - Do not validate buy price or quantity against target.

- [ ] **Step 3: Implement persistent alert state and evaluator**
  - Persist armed/rearm state keyed by account, symbol, and active target revision so backend restarts do not duplicate alerts.
  - Resolve the previous completed trading date from DuckDBStore.
  - Query closes through DuckDBStore only.
  - Emit the domain event; do not send email or implement channel configuration.

- [ ] **Step 4: Integrate evaluator after successful market refresh**
  - Run once after the relevant market data update and derived-cache refresh.
  - Make the evaluation idempotent for the same valuation date.
  - Do not block market update completion on a future notification transport implementation.

- [ ] **Step 5: Run focused tests**

```bash
python -m pytest backend/tests/test_portfolio_holdings_service.py backend/tests/test_buy_opportunity.py backend/tests/test_scheduler.py -q
```

---

### Task 5: Unified Portfolio v1 frontend

**Files:**
- Modify: `frontend/src/types/portfolio.ts`
- Modify: `frontend/src/api/portfolio.ts`
- Modify: `frontend/src/pages/PortfolioPage.tsx`
- Modify: `frontend/src/pages/__tests__/PortfolioPage.test.tsx`
- Modify: `frontend/src/components/backtest/BacktestResult.tsx`
- Modify: `frontend/src/components/backtest/BacktestHistory.tsx`
- Test: `frontend/src/api/__tests__/portfolio.test.ts`

**Interfaces:**
- Account responses expose optional strategy binding and execution status.
- Snapshot/holdings responses expose `targetQuantity`, `referencePrice`, `remainingQuantity`, `overTargetQuantity`, `targetStatus`, and `alertStatus`.
- Backtest result/history provides the action to create and bind the selected successful task to an account.

- [ ] **Step 1: Add failing frontend tests**
  - Render ordinary unbound accounts without strategy columns.
  - Render bound strategy accounts with target and remaining columns.
  - Show exited targets with actual holdings but no buy alert.
  - Hide fully sold positions from active holdings while retaining history views.
  - Bind action marks the task as execution active and moves it to the top of history.

- [ ] **Step 2: Implement API/type mappings for `/api/v1/portfolio`**
  - Keep camelCase frontend types and snake_case wire payloads.
  - Add bind/unbind and enriched snapshot/holdings methods.
  - Do not call the old `/api/portfolio` endpoints.

- [ ] **Step 3: Implement the unified page overlay**
  - Add strategy metadata only when account is bound.
  - Keep trade entry controls and ordinary holdings behavior unchanged.
  - Add explicit bind/unbind controls and target status labels.

- [ ] **Step 4: Run frontend tests and checks**

```bash
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

---

### Task 6: Remove the old Portfolio interface and migrate scheduler

**Files:**
- Modify: `backend/scheduler.py`
- Modify: `backend/main.py`
- Delete: `backend/routers/portfolio.py`
- Delete or replace: `backend/services/portfolio/manager.py`
- Delete or migrate: `backend/services/portfolio/db.py`
- Delete: `backend/tests/test_portfolio_api.py`
- Replace: `backend/tests/test_portfolio_manager.py`

- [ ] **Step 1: Write migration tests**
  - Scheduler snapshots use the new account/holdings service.
  - No production route registers `/api/portfolio`.
  - Existing backtest and chat tables remain intact in the shared SQLite database.

- [ ] **Step 2: Migrate scheduler snapshot behavior**
  - Use DuckDBStore for latest market closes.
  - Write snapshots through the new Portfolio v1 service.
  - Preserve the existing 15:30 snapshot schedule.

- [ ] **Step 3: Remove old route and manager after new tests pass**
  - Do not add a compatibility wrapper.
  - Keep only the new `/api/v1/portfolio` interface.

- [ ] **Step 4: Run the complete verification suite**

```bash
python -m pytest backend/tests/ -x -q
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

## Plan Self-Review

- Execution metadata is separate from backtest run status and is covered in Task 1.
- Task result remains immutable; target materialization is covered in Task 3.
- Latest target selection by `effective_date <= as_of_date` is covered in Task 3.
- Account buy restriction, unrestricted price/quantity, over-target state, exits, and realized P&L are covered in Task 4.
- Previous-trading-day close, crossing/rearm behavior, persistence, and notification seam are covered in Task 4.
- Unified UI and active-task ordering under return sorting are covered in Tasks 1 and 5.
- Old interface removal is deferred until the new interface and scheduler are tested in Task 6.
