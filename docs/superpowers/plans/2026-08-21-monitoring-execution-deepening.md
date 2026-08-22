# Monitoring Execution Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deepen the Backtest execution module so full backtests and scan runs share one lifecycle seam, while Monitoring invokes scan mode for a six-month window without owning backtest internals.

**Architecture:** Add a Backtest execution module with a small typed execution specification and mode-specific payloads. The module owns `backtest_tasks` creation, progress, completion, and failure; `full` and `scan` remain separate implementations behind the same lifecycle seam. Monitoring remains responsible for scheduling and its own `monitoring_strategy_runs` record, linking to the returned task ID without becoming the owner of the backtest result.

**Tech Stack:** Python 3.10, FastAPI, SQLite, pandas, DuckDB-backed `data_cache`, `BacktestEngine`, pytest, React 19, TypeScript, Vitest.

**Spec:** `/var/folders/rt/1qwqk1rn5333pfz8sprmp30w0000gn/T/architecture-review-20260821-architecture.html` (candidate 1; decisions recorded in conversation)

## Global Constraints

- `Strategy` remains the single strategy model; do not reintroduce StrategyGroup or the old screener/buyer/seller split.
- `BacktestEngine.run()` remains the full portfolio simulation path; `BacktestEngine.run_scan()` remains the selection observation path.
- Monitoring runs always use scan mode with `start_date = as_of_date - 182 days` and `end_date = as_of_date`.
- Full and scan result payloads remain distinct; only task lifecycle and shared execution metadata are unified.
- `monitoring_strategy_runs` and `backtest_tasks` remain parallel records linked by nullable `task_id`; neither becomes a database master record.
- Preserve existing monitoring routes, backtest routes, database columns, `task_type="monitor"`, and frontend history behavior.
- All business data access continues through DuckDB/data_cache; do not read parquet directly.
- Long-running backtests must remain background work.

---

### Task 1: Define the Backtest execution seam

**Files:**
- Create: `backend/services/backtest/execution.py`
- Test: `backend/tests/test_backtest_execution.py`

**Interfaces:**
- Consumes: `BacktestDataSnapshot`, `BacktestEngine`, `TaskManager`, and strategy loader inputs.
- Produces: `ExecutionSpec`, `ExecutionMode`, `submit_execution(spec) -> str`, and mode-specific result payloads without changing existing JSON shapes.

- [ ] **Step 1: Write failing tests for execution specifications and lifecycle behavior**

  Cover these concrete behaviors:

  ```python
  def test_scan_spec_uses_scan_engine_and_persists_monitor_metadata():
      spec = ExecutionSpec(
          execution_mode="scan",
          task_type="monitor",
          strategy_class="FakeStrategy",
          filepath="/trusted/fake.py",
          params={},
          market="A",
          symbols=None,
          start_date="2026-02-18",
          end_date="2026-08-19",
          pipeline_info={"trigger_source": "monitor"},
      )
      task_id = execution.submit(spec)
      assert task_id == "task-1"
      assert fake_task_manager.completed["task-1"]["hits"] == ["600000"]
  ```

  Also test that `execution_mode="full"` calls `BacktestEngine.run()` and that an exception calls `fail_task()` exactly once.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

  Run:

  ```bash
  python -m pytest backend/tests/test_backtest_execution.py -q
  ```

  Expected: failures because `execution.py` and its execution seam do not exist yet.

- [ ] **Step 3: Implement the smallest typed execution seam**

  Add a dataclass carrying strategy, data window, market, symbols, mode, task type, and `pipeline_info`. The implementation must:

  - create one `backtest_tasks` row before background execution;
  - load the strategy and create the existing snapshot;
  - call `run_scan()` only for `scan` mode;
  - call `run()` only for `full` mode;
  - preserve existing scan aggregation and full result serialization;
  - call `complete_task()` with the mode-specific payload;
  - call `fail_task()` and retain the task ID on all failures.

  Keep the worker asynchronous at the submission seam, but make the actual execution function synchronous and directly testable.

- [ ] **Step 4: Run the focused tests and verify they pass**

  Run:

  ```bash
  python -m pytest backend/tests/test_backtest_execution.py -q
  ```

  Expected: all new execution seam tests pass.

- [ ] **Step 5: Inspect the isolated execution diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 2: Move scan aggregation out of the router

**Files:**
- Modify: `backend/services/backtest/execution.py`
- Modify: `backend/routers/backtest.py`
- Modify: `backend/services/monitoring/strategy_monitor.py`
- Test: `backend/tests/test_strategy_monitor.py`
- Test: `backend/tests/test_backtest_api.py`

**Interfaces:**
- Consumes: `ExecutionSpec` and the existing `BacktestEngine` payloads.
- Produces: one internal scan-result adapter owned by the Backtest execution module; no monitoring import from `routers.backtest`.

- [ ] **Step 1: Add a failing regression test proving Monitoring has no router-private dependency**

  Patch the existing monitor execution test so it provides the execution adapter seam and deliberately makes `routers.backtest._aggregate_scan_hits` unavailable. Assert the monitor still returns a scan payload with `hits`, `date_range`, and `task_id`.

- [ ] **Step 2: Run the regression test and verify it fails against the current import**

  ```bash
  python -m pytest backend/tests/test_strategy_monitor.py::test_monitor_execution_persists_six_month_history_task -q
  ```

  Expected: failure because current Monitoring imports the router-private aggregation helper.

- [ ] **Step 3: Move the aggregation implementation behind the Backtest execution seam**

  Relocate the existing hit aggregation behavior without changing its JSON keys: `symbol`, `name`, `current_price`, `signal_close`, `change_pct_since_signal`, `last_match_date`, `match_count`, and `factors`. Update the scan-radar router to consume the shared implementation and delete the Monitoring-to-router import.

- [ ] **Step 4: Run backend monitoring and radar tests**

  ```bash
  python -m pytest backend/tests/test_strategy_monitor.py backend/tests/test_backtest_api.py -q
  ```

  Expected: all tests pass and no result shape changes occur.

- [ ] **Step 5: Inspect the scan seam extraction diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 3: Route Monitoring through scan execution

**Files:**
- Modify: `backend/services/monitoring/strategy_monitor.py`
- Modify: `backend/routers/monitoring.py`
- Modify: `backend/services/backtest/execution.py`
- Test: `backend/tests/test_strategy_monitor.py`
- Test: `backend/tests/test_monitoring_api.py`

**Interfaces:**
- Consumes: `ExecutionSpec(execution_mode="scan")` and the shared submission seam.
- Produces: Monitoring run records linked to the returned task ID; complete result remains in `backtest_tasks`.

- [ ] **Step 1: Add failing tests for parallel record semantics**

  Assert that a triggered monitor:

  - creates one `monitoring_strategy_runs` row;
  - creates one `backtest_tasks` row with `task_type="monitor"` and `trigger_source="monitor"`;
  - uses a six-month date range;
  - writes `task_id` back to the monitoring run on success;
  - writes the same link and failed status when execution fails after task creation;
  - does not copy the full payload into a second canonical result store.

- [ ] **Step 2: Run the tests and verify they fail against direct TaskManager orchestration**

  ```bash
  python -m pytest backend/tests/test_strategy_monitor.py backend/tests/test_monitoring_api.py -q
  ```

- [ ] **Step 3: Replace direct BacktestEngine/TaskManager work in Monitoring**

  Make Monitoring construct an `ExecutionSpec` and call the shared submission seam. Keep scheduling concerns local: due-date calculation, claim/reclaim, and next-run advancement stay in Monitoring. Remove strategy loading, snapshot construction, hit aggregation, and task lifecycle details from `strategy_monitor.py`.

- [ ] **Step 4: Run the focused backend tests**

  ```bash
  python -m pytest backend/tests/test_strategy_monitor.py backend/tests/test_monitoring_api.py backend/tests/test_backtest_task_manager.py -q
  ```

- [ ] **Step 5: Inspect the Monitoring integration diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 4: Route existing full and scan endpoints through the seam

**Files:**
- Modify: `backend/routers/backtest.py`
- Modify: `backend/services/backtest/execution.py`
- Test: `backend/tests/test_backtest_api.py`
- Test: `backend/tests/test_backtest_api.py`, `backend/tests/test_engine.py`

**Interfaces:**
- Consumes: the shared execution submission seam.
- Produces: unchanged `/api/backtest/run` full payloads and `/api/backtest/scan-radar` scan payloads.

- [ ] **Step 1: Add endpoint regression assertions**

  Assert that `/api/backtest/run` builds `execution_mode="full"`, while `/api/backtest/scan-radar` builds `execution_mode="scan"`, and both preserve existing task metadata and result fields.

- [ ] **Step 2: Run the endpoint tests before migration**

  ```bash
  python -m pytest backend/tests/test_backtest_api.py backend/tests/test_engine.py -q
  ```

- [ ] **Step 3: Replace duplicated thread/task orchestration in both routes**

  Keep request validation and route-specific date resolution in the routers. Delegate task creation, background execution, serialization, completion, and failure to the shared execution module.

- [ ] **Step 4: Run the endpoint tests after migration**

  ```bash
  python -m pytest backend/tests/test_backtest_api.py backend/tests/test_engine.py -q
  ```

- [ ] **Step 5: Inspect endpoint integration diff**

  ```bash
  git diff --check
  git status --short
  ```

### Task 5: Verify frontend history compatibility and full regression

**Files:**
- Modify only if a compatibility adjustment is required: `frontend/src/api/backtestEngine.ts`, `frontend/src/components/backtest/BacktestHistory.tsx`, `frontend/src/components/backtest/BacktestDetail.tsx`
- Test: `frontend/src/components/backtest/__tests__/BacktestHistory.test.tsx`

**Interfaces:**
- Consumes: unchanged task list/result JSON with `task_type="backtest"`, `task_type="scan-radar"`, and `task_type="monitor"`.
- Produces: existing full-result and radar-result renderers selected by execution mode/task type.

- [ ] **Step 1: Run existing frontend history tests before changing UI code**

  ```bash
  cd frontend && npm test -- --run src/components/backtest/__tests__/BacktestHistory.test.tsx
  ```

- [ ] **Step 2: Add only the smallest compatibility assertion needed**

  Verify that monitor tasks still show the strategy name, `监控触发`, date range, and radar hits; full tasks still open `BacktestResult`; scan tasks still open `RadarResultView`.

- [ ] **Step 3: Run frontend validation**

  ```bash
  cd frontend && npm test
  cd frontend && npx tsc --noEmit
  cd frontend && npm run lint
  ```

- [ ] **Step 4: Run complete backend validation**

  ```bash
  python -m pytest backend/tests/ -x -q
  ```

- [ ] **Step 5: Inspect the final diff**

  ```bash
  git diff --check
  git status --short
  git diff --check
  git status --short
  ```

## Self-Review Checklist

- `Strategy` remains unchanged and is shared by full and scan modes.
- Full and scan payloads remain distinct.
- Monitoring no longer imports a private function from `routers.backtest`.
- `monitoring_strategy_runs` and `backtest_tasks` remain parallel records.
- Every monitor trigger creates a result task, including failures after task creation.
- Existing routes and database fields remain compatible.
- No data snapshot persistence is introduced in this plan.
- No direct parquet reads are introduced.
