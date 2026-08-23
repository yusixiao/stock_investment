# TaskManager Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split TaskManager's SQLite persistence, result encoding, and in-memory progress into focused internal modules while preserving every existing caller contract.

**Architecture:** Keep `TaskManager` as the compatibility facade. Extract `TaskProgressStore`, `TaskResultCodec`, and `TaskRepository`; the facade coordinates them and continues exposing the current methods and return shapes. Account binding remains behind the facade in this phase.

**Tech Stack:** Python 3.10+, SQLite, JSON, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-task-manager-split-design.md`

## Global Constraints

- Do not modify the `backtest_tasks` schema.
- Do not change full, scan, or monitor result payloads.
- Do not remove `source_task_id` or `deleted` compatibility fields.
- Do not change the public `TaskManager` constructor, method names, parameters, or return values.
- DuckDB remains the only business market-data entry point; this change does not add market-data access.
- Do not commit or push as part of implementation.

---

### Task 1: Extract Progress Store

**Files:**
- Create: `backend/services/backtest/task_progress.py`
- Modify: `backend/services/backtest/task_manager.py:11-16,94-96,128-134,200-201,225-226,238-243`
- Test: `backend/tests/test_backtest_task_manager.py`

**Interfaces:**
- Produces `TaskProgressStore.update(task_id, current, total, phase)`, `.get(task_id)`, and `.remove(task_id)`.
- `TaskManager` delegates progress operations to one injected/default `TaskProgressStore` and keeps the same `get_status()` response.

- [ ] **Step 1: Write the failing test**

Add a test that constructs two `TaskProgressStore` instances, updates one, and asserts the other has no progress; also assert `remove()` clears the first store.

```python
def test_progress_store_isolated_and_thread_safe():
    first = TaskProgressStore()
    second = TaskProgressStore()
    first.update("task-1", 2, 10, "扫描中")
    assert first.get("task-1") == {"current": 2, "total": 10, "phase": "扫描中"}
    assert second.get("task-1") is None
    first.remove("task-1")
    assert first.get("task-1") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/test_backtest_task_manager.py -k progress_store -q`

Expected: FAIL because `TaskProgressStore` does not exist.

- [ ] **Step 3: Implement the minimal store and delegate facade methods**

Move only the lock and `_progress` dictionary into `TaskProgressStore`; keep dictionary values and missing-task behaviour unchanged. `TaskManager.get_status()` must still return `task_id`, `status`, and optional `progress`.

- [ ] **Step 4: Run focused verification**

Run: `pytest backend/tests/test_backtest_task_manager.py backend/tests/test_task_manager.py -q`

Expected: all tests pass.

### Task 2: Extract Result Codec

**Files:**
- Create: `backend/services/backtest/task_result_codec.py`
- Modify: `backend/services/backtest/task_manager.py:54-73,136-161,163-196,245-281,349-400`
- Test: `backend/tests/test_backtest_task_manager.py`, `backend/tests/test_task_result_codec.py`

**Interfaces:**
- Produces `TaskResultCodec.encode(value) -> str`, `decode(value) -> object`, `build_summary(result) -> str`, and `date_range(result) -> tuple[str | None, str | None]`.
- The codec owns JSON `ensure_ascii=False`, malformed/empty compatibility behaviour, full metrics summary, scan hits summary, screened-symbol summary, and scan date range extraction.

- [ ] **Step 1: Write failing codec tests**

Cover scan, full, and screener summaries plus malformed/empty JSON compatibility.

```python
def test_codec_builds_scan_summary_and_date_range():
    result = {"hits": ["A"], "total_scanned": 3, "lookback_used": 182,
              "date_range": {"start": "2026-01-01", "end": "2026-08-01"}}
    codec = TaskResultCodec()
    assert json.loads(codec.build_summary(result)) == {
        "hit_count": 1, "total_scanned": 3, "lookback_used": 182,
    }
    assert codec.date_range(result) == ("2026-01-01", "2026-08-01")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_task_result_codec.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement codec and replace facade-local parsing**

`TaskManager.complete_task()` must use `build_summary()` and `date_range()`. `get_result()` and `list_tasks()` must use `decode()` while preserving omitted-vs-null fields and all legacy fields.

- [ ] **Step 4: Run focused and compatibility tests**

Run: `pytest backend/tests/test_task_result_codec.py backend/tests/test_backtest_task_manager.py backend/tests/test_task_manager.py backend/tests/test_backtest_api.py -q`

Expected: all tests pass with unchanged task JSON shapes.

### Task 3: Extract SQLite Repository

**Files:**
- Create: `backend/services/backtest/task_repository.py`
- Modify: `backend/services/backtest/task_manager.py:12-126,163-227,228-347,349-400`
- Test: `backend/tests/test_task_repository.py`, `backend/tests/test_backtest_task_manager.py`

**Interfaces:**
- Produces `TaskRepository(db_path)`, `_get_conn()`, `create_task_row(...)`, `update_task_result(...)`, `fail_task(...)`, `get_status(...)`, `get_result_row(...)`, `list_task_rows(...)`, `delete_task(...)`, and account-binding transaction methods.
- Repository methods return SQLite rows or persistence values; they do not decode JSON and do not touch progress state.

- [ ] **Step 1: Write failing repository tests**

Use a temporary SQLite database and assert task creation, result update, failure update, soft delete, and list ordering through the repository.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_task_repository.py -q`

Expected: FAIL because `TaskRepository` does not exist.

- [ ] **Step 3: Implement repository by moving SQL without changing SQL semantics**

Keep `init_backtest_tables`, startup recovery of `running` tasks, transaction boundaries, column selection, and account conflict checks identical to the current implementation. Move connection creation into the repository.

- [ ] **Step 4: Run repository and existing task tests**

Run: `pytest backend/tests/test_task_repository.py backend/tests/test_backtest_task_manager.py backend/tests/test_task_manager.py backend/tests/test_portfolio_account_service.py backend/tests/test_strategy_targets.py -q`

Expected: all tests pass.

### Task 4: Compose the Compatibility Facade

**Files:**
- Modify: `backend/services/backtest/task_manager.py`
- Modify: `backend/services/backtest/execution.py` only if constructor injection requires it
- Test: `backend/tests/test_backtest_execution.py`, `backend/tests/test_backtest_api.py`, `backend/tests/test_strategy_monitor.py`

**Interfaces:**
- Consumes `TaskRepository`, `TaskResultCodec`, and `TaskProgressStore` from Tasks 1-3.
- Preserves `TaskManager(db_path=None)` and all existing public methods and output shapes.

- [ ] **Step 1: Add facade composition tests**

Construct `TaskManager` with isolated collaborators and assert `create_task()`, `complete_task()`, `fail_task()`, `get_status()`, `get_result()`, and `list_tasks()` use the collaborators while returning the existing structures.

- [ ] **Step 2: Run tests to verify the new composition contract fails**

Run: `pytest backend/tests/test_backtest_execution.py backend/tests/test_backtest_api.py backend/tests/test_strategy_monitor.py -q`

Expected: FAIL only for the new collaborator-injection assertions.

- [ ] **Step 3: Replace facade implementation with delegation**

Keep account-binding methods as facade delegates to `TaskRepository`; keep module-level `task_manager = TaskManager()` for existing imports. Do not alter execution seam or router contracts.

- [ ] **Step 4: Run complete focused verification**

Run: `pytest backend/tests/test_task_result_codec.py backend/tests/test_task_repository.py backend/tests/test_backtest_task_manager.py backend/tests/test_task_manager.py backend/tests/test_backtest_execution.py backend/tests/test_backtest_api.py backend/tests/test_strategy_monitor.py backend/tests/test_portfolio_account_service.py backend/tests/test_strategy_targets.py -q`

Expected: all tests pass.

### Task 5: Full Regression and Review

**Files:**
- Modify only files required by findings from Tasks 1-4.
- Test: `backend/tests/`

- [ ] **Step 1: Run formatting/diff checks**

Run: `git diff --check`.

- [ ] **Step 2: Run backend full suite in the background**

Run: `nohup python -m pytest backend/tests/ -x -q > /tmp/task-manager-split-backend.log 2>&1 &`

Then inspect the PID and log until completion. Expected: no new failures; existing unrelated warnings must be reported rather than hidden.

- [ ] **Step 3: Review compatibility surface**

Check that no caller imports the extracted modules as public API, `TaskManager` remains the only existing import seam, and no schema or payload changes appear in the diff.
