# RefreshRunner Single Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `RefreshRunner` the only runtime module that orchestrates market update, DuckDB view refresh, data cache rebuild, version advancement, and refresh state transitions.

**Architecture:** Keep `scheduler.py` as the APScheduler composition root: it triggers `RefreshRunner`, schedules retry dates, and runs business subscribers after completion. Move all refresh-stage side effects behind the existing `RefreshRunner` interface, remove `_post_market_update_refresh()`, and preserve the existing completion callback instead of introducing an event bus.

**Tech Stack:** Python 3.10, APScheduler, SQLite, DuckDB, pandas, pytest, FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-22-refresh-runner-orchestrator-design.md`

## Global Constraints

- `RefreshRunner` is the only runtime owner of `update_market/update_markets`, `refresh_view`, `data_cache.invalidate`, `data_cache.load_market_async`, cache readiness, market version advancement, and refresh state writes.
- `scheduler.py` may register jobs, create/call `RefreshRunner`, schedule retry dates, and run post-refresh business subscribers; it must not implement a second refresh flow.
- Do not change updater behavior, refresh state schema, scheduler job IDs, 06:00 schedule, retry count, or retry interval.
- Preserve `completed`, `partial`, and `stale` semantics and only notify subscribers for markets whose update/view/cache stages are ready.
- Preserve `RefreshRunner.start()`, `RefreshRunner.run()`, `on_complete`, and the manual `/api/market-update/trigger` contract.
- Do not introduce an event bus, message queue, direct parquet reads, or changes to strategy/portfolio business rules.
- Do not create git commits during implementation unless explicitly requested.

---

### Task 1: Harden the RefreshRunner lifecycle contract

**Files:**
- Modify: `backend/services/market_data/refresh_runner.py`
- Test: `backend/tests/test_market_refresh_runner.py`

**Interfaces:**
- Consumes: existing injected `update_market`, `update_markets`, `refresh_view`, `refresh_cache`, `refresh_before_cache`, and `on_complete` adapters.
- Produces: the same `RefreshRunner.start()` and `run()` interface, with explicit guarantees that pre-cache failure, cache failure, version advancement, and completion callback ordering are stable.

- [ ] **Step 1: Add failing lifecycle tests**

  Add tests that assert:

  ```python
  def test_refresh_before_cache_receives_only_successful_markets(): ...
  def test_refresh_before_cache_failure_marks_successful_markets_stale(): ...
  def test_completion_callback_sees_final_refresh_record(): ...
  def test_cache_failure_does_not_advance_market_version(): ...
  ```

  Use injected fake adapters and an isolated `RefreshStateStore`; do not load real market data.

- [ ] **Step 2: Run the focused tests and verify the expected red failures**

  ```bash
  python -m pytest backend/tests/test_market_refresh_runner.py -q
  ```

  Expected: the new assertions fail only where the current lifecycle does not guarantee the documented behavior.

- [ ] **Step 3: Implement the smallest lifecycle correction**

  Keep the existing stage names and database fields. Ensure `refresh_before_cache` receives exactly the successful update set, a failure prevents those markets from being treated as ready, and `on_complete(self.store.get(refresh_id))` runs only after `finish_refresh()`.

- [ ] **Step 4: Run the focused runner tests**

  ```bash
  python -m pytest backend/tests/test_market_refresh_runner.py -q
  ```

- [ ] **Step 5: Inspect the diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 2: Remove the scheduler refresh duplicate

**Files:**
- Modify: `backend/scheduler.py`
- Test: `backend/tests/test_scheduler.py`
- Test: `backend/tests/test_scheduler_market_retry.py`

**Interfaces:**
- Consumes: `RefreshRunner` completion record and existing `run_due_strategy_monitors`, `evaluate_stock_price_monitors`, and buy-opportunity interfaces.
- Produces: one main-refresh path and one retry path that both invoke the same RefreshRunner lifecycle and only perform business post-processing in callbacks.

- [ ] **Step 1: Add failing scheduler regression tests**

  Add assertions that:

  ```python
  def test_scheduler_does_not_call_legacy_post_refresh_helper(monkeypatch): ...
  def test_main_refresh_passes_circulating_shares_as_runner_pre_cache_hook(): ...
  def test_retry_refresh_uses_same_pre_cache_and_completion_contract(): ...
  def test_completion_subscribers_receive_only_ready_markets(): ...
  ```

  The tests should monkeypatch `_make_refresh_runner` and inspect injected callbacks/arguments rather than run network updates.

- [ ] **Step 2: Run scheduler tests and verify the new regression tests fail**

  ```bash
  python -m pytest backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py -q
  ```

- [ ] **Step 3: Remove `_post_market_update_refresh()` and consolidate callback assembly**

  Make `_market_update_job()` and `_market_retry_job()` both pass the same `_refresh_circulating_shares` pre-cache hook and the same `_on_market_refresh_complete` post-processing callback shape. Keep retry scheduling based only on `record.market_states[market].update.detail.aborted`.

  Do not add `data_cache.invalidate()` or `data_cache.load_market_async()` to scheduler callbacks. After the edit, these names may remain only in unrelated scheduler-free tests/docs, not in `backend/scheduler.py` runtime code.

- [ ] **Step 4: Run scheduler and retry tests**

  ```bash
  python -m pytest backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py backend/tests/test_market_refresh_runner.py -q
  ```

- [ ] **Step 5: Inspect the scheduler diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 3: Verify manual refresh entry point compatibility

**Files:**
- Modify only if required: `backend/routers/market_update.py`
- Test: `backend/tests/test_market_refresh_api.py`

**Interfaces:**
- Consumes: `RefreshRunner.start(source="manual", markets=...)`.
- Produces: unchanged manual trigger response with `message`, `market`, and `refresh_id`; no second refresh implementation.

- [ ] **Step 1: Add or update manual trigger assertions**

  Verify both `market=None` and a single market pass the expected list to `RefreshRunner.start()`, and invalid markets still return HTTP 400.

- [ ] **Step 2: Run the manual refresh API tests**

  ```bash
  python -m pytest backend/tests/test_market_refresh_api.py -q
  ```

- [ ] **Step 3: Confirm runtime ownership with targeted searches**

  ```bash
  rg "data_cache\.(invalidate|load_market_async)" backend/scheduler.py
  rg "_post_market_update_refresh" backend
  ```

  Expected: no runtime references from `backend/scheduler.py`; the legacy helper has no references after removal.

- [ ] **Step 4: Inspect the manual-entry diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 4: Full refresh-chain verification

**Files:**
- No planned production changes; modify only tests if a regression assertion discovered in Tasks 1–3 needs to be captured.
- Test: `backend/tests/test_market_refresh_runner.py`
- Test: `backend/tests/test_scheduler.py`
- Test: `backend/tests/test_scheduler_market_retry.py`
- Test: `backend/tests/test_market_refresh_api.py`

**Interfaces:**
- Consumes: final RefreshRunner, scheduler, retry, and manual refresh behavior.
- Produces: evidence that only RefreshRunner owns refresh orchestration and existing business subscribers remain compatible.

- [ ] **Step 1: Run the complete refresh-chain regression set**

  ```bash
  python -m pytest backend/tests/test_market_refresh_runner.py backend/tests/test_scheduler.py backend/tests/test_scheduler_market_retry.py backend/tests/test_market_refresh_api.py backend/tests/test_market_refresh_state.py -q
  ```

- [ ] **Step 2: Run the complete backend suite in the background**

  ```bash
  nohup python -m pytest backend/tests/ -x -q > /tmp/refresh-runner-backend-pytest.log 2>&1 &
  ```

  Check the PID and log until the process exits; do not run a real market refresh in the foreground.

- [ ] **Step 3: Check the final ownership and diff**

  ```bash
  rg "data_cache\.(invalidate|load_market_async)" backend/scheduler.py
  rg "_post_market_update_refresh" backend
  git diff --check
  git status --short
  ```

- [ ] **Step 4: Record deferred warnings without changing scope**

  Record any pre-existing pytest deprecation or thread-isolation warnings separately. Do not add an event bus, alter updater logic, or refactor unrelated scheduled jobs as part of this plan.

## Self-Review Checklist

- The spec's lifecycle, non-goals, failure semantics, compatibility requirements, and acceptance criteria each map to a task above.
- No task introduces a new event bus or changes the public RefreshRunner/manual refresh interface.
- Main and retry refreshes share the same RefreshRunner lifecycle and pre-cache hook.
- Scheduler completion callbacks only run business subscribers.
- `_post_market_update_refresh()` is removed rather than wrapped for compatibility.
- All test commands use injected adapters or the existing test suite and never read real market data.
