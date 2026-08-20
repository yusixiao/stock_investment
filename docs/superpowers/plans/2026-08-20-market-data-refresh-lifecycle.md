# Market Data Refresh Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 A/HK/US 市场更新、DuckDB 可读性和 data_cache 可用性之间的 refresh lifecycle，保证同一时刻只有一个 refresh、市场可独立完成、旧 cache 不被新任务覆盖，并记录最近 3 次 refresh 状态。

**Architecture:** 新增一个小的 refresh lifecycle module 作为状态与编排 seam，不替换现有 updater、DuckDBStore 或 data_cache implementation。一个全局 `refresh_id` 关联每个市场的 update/view/cache 阶段和市场版本；市场只有在 cache 构建成功后才推进版本。stale cache 仍可被业务使用，但状态和数据版本必须随结果暴露。

**Tech Stack:** Python 3.10、FastAPI、SQLite、DuckDB、pytest、threading/APScheduler。

**Spec:** 本计划承接已确认的 market_data 数据平面设计：不排队；运行中的 refresh 拒绝新触发；市场独立可用；同一 refresh_id 包含市场小版本；保留最近 3 次；stale 可使用但显式标记；邮件通知不在本阶段实现。

## Global Constraints

- DuckDB 是业务数据唯一查询入口；禁止新增业务代码直接读取 Parquet。
- 物理业务数据只能位于 `data/market/`。
- 不恢复 StrategyGroup 或旧 Screener/Buyer/Seller 三角模型。
- 不新增邮件、SMTP 或通知配置；通知作为后续独立 module。
- 不启动全市场更新作为测试；所有状态测试使用 in-process fake runner。
- 任何长任务保持后台执行；本计划只改编排和状态，不执行真实批量更新。
- 复杂逻辑添加简洁中文注释，敏感配置不写入日志。

---

### Task 1: Add refresh state persistence

**Files:**
- Create: `backend/services/market_data/refresh_state.py`
- Modify: `backend/services/db_schema.py`
- Modify: `backend/services/market_data/AGENTS.md` only if the final state names need documenting
- Test: `backend/tests/test_market_refresh_state.py`

**Interfaces:**
- Produces `RefreshStateStore.start_refresh(source: str) -> RefreshRecord`.
- Produces `RefreshStateStore.get_active() -> RefreshRecord | None`.
- Produces `RefreshStateStore.record_market_stage(refresh_id: str, market: str, stage: str, status: str, detail: dict | None = None) -> None`.
- Produces `RefreshStateStore.finish_market(refresh_id: str, market: str, market_version: int | None, cache_status: str, stale: bool) -> None`.
- Produces `RefreshStateStore.get_recent(limit: int = 3) -> list[RefreshRecord]`.
- Uses a dedicated SQLite table created idempotently from `services/db_schema.py`; it must not reuse `backtest_tasks`.

- [ ] **Step 1: Write failing tests for refresh exclusivity and retention**

```python
def test_start_refresh_rejects_when_one_is_running(db_conn):
    store = RefreshStateStore(db_conn)
    first = store.start_refresh("manual")

    with pytest.raises(RefreshAlreadyRunning) as exc:
        store.start_refresh("scheduler")

    assert exc.value.refresh_id == first.refresh_id


def test_recent_records_keep_only_three_finished_refreshes(db_conn):
    store = RefreshStateStore(db_conn)
    for _ in range(4):
        record = store.start_refresh("manual")
        store.finish_refresh(record.refresh_id, "completed")

    rows = store.get_recent()
    assert len(rows) == 3
```

- [ ] **Step 2: Run the focused tests and verify the expected missing-module failure**

Run: `python -m pytest backend/tests/test_market_refresh_state.py -q`

Expected: FAIL because `refresh_state.py` and the refresh table do not exist yet.

- [ ] **Step 3: Add the idempotent SQLite schema and minimal state implementation**

The table must store at least `refresh_id`, `source`, `status`, `created_at`, `started_at`, `finished_at`, `error`, and a serialized market-state payload. `start_refresh` must use a transaction to check for an existing `running` record before inserting. `finish_refresh` must update the record and delete older completed/interrupted rows so only the newest three finished records remain.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest backend/tests/test_market_refresh_state.py -q`

Expected: PASS.

- [ ] **Step 5: Add tests for interrupted recovery and per-market stage records**

Assert that startup recovery changes `running` records to `interrupted`, and that one refresh can hold independent A/HK/US stage payloads without changing the other markets.

- [ ] **Step 6: Run the focused tests again**

Run: `python -m pytest backend/tests/test_market_refresh_state.py -q`

Expected: PASS.

---

### Task 2: Add a single refresh runner seam

**Files:**
- Create: `backend/services/market_data/refresh_runner.py`
- Modify: `backend/routers/market_update.py`
- Modify: `backend/scheduler.py`
- Modify: `backend/services/market_data/updaters/market_updater.py` only where a runner callback is needed
- Test: `backend/tests/test_market_refresh_runner.py`

**Interfaces:**
- Produces `RefreshRunner.start(source: str, markets: list[str] | None = None) -> RefreshRecord`.
- Produces `RefreshRunner.run(refresh_id: str, markets: list[str]) -> None` for the already-started background execution.
- The runner rejects a second start while any refresh is running; it never queues or runs overlapping refreshes.
- It records `update`, `view`, and `cache` stages per market.
- It leaves notification delivery out of the implementation; future notification module will consume final records.

- [ ] **Step 1: Write failing tests for no-overlap and market independence**

```python
def test_runner_rejects_second_refresh_while_first_is_running(fake_runner, db_conn):
    runner = RefreshRunner(db_conn, update_market=fake_runner.blocking_update)
    first = runner.start("manual", ["A", "HK", "US"])

    with pytest.raises(RefreshAlreadyRunning) as exc:
        runner.start("scheduler", ["A"])

    assert exc.value.refresh_id == first.refresh_id


def test_one_market_failure_does_not_fail_other_markets(fake_runner, db_conn):
    fake_runner.fail_markets = {"HK"}
    runner = RefreshRunner(db_conn, update_market=fake_runner.update)

    record = runner.start("scheduler", ["A", "HK", "US"])
    runner.run(record.refresh_id, ["A", "HK", "US"])

    states = runner.store.get_market_states(record.refresh_id)
    assert states["A"].status == "ready"
    assert states["HK"].status == "failed"
    assert states["US"].status == "ready"
```

- [ ] **Step 2: Run tests and confirm failure before implementation**

Run: `python -m pytest backend/tests/test_market_refresh_runner.py -q`

Expected: FAIL because the runner and state transitions are not implemented.

- [ ] **Step 3: Implement the minimal runner around existing updater functions**

Use the existing `update_all_markets`/`update_single_market` result objects. Do not move data-fetching logic into the runner. The runner only owns refresh exclusivity, per-market stage transitions, version lookup, and final status calculation. A market that fails may retain its previous cache and is recorded as `stale`; it must not be treated as a new ready version.

- [ ] **Step 4: Run focused runner tests**

Run: `python -m pytest backend/tests/test_market_refresh_runner.py -q`

Expected: PASS.

- [ ] **Step 5: Route both manual and scheduler triggers through the same runner**

Replace direct daemon-thread calls in `routers/market_update.py` and `_market_update_job()` with the same runner start path. A rejected trigger returns the active `refresh_id` and a deterministic conflict response; it does not create a queued task.

- [ ] **Step 6: Add route/scheduler integration tests**

Assert that manual and scheduler sources both create the same record shape and that a second trigger is rejected without invoking an updater.

---

### Task 3: Add cache generation protection and stale metadata

**Files:**
- Modify: `backend/services/backtest/data_cache.py`
- Modify: `backend/services/market_data/refresh_runner.py`
- Test: `backend/tests/test_data_cache_generation.py`
- Test: `backend/tests/test_market_refresh_runner.py`

**Interfaces:**
- `data_cache.load_market_async(market, generation: int | None = None, refresh_id: str | None = None) -> dict` keeps its existing call compatibility while accepting the generation metadata.
- `data_cache.get_status(market) -> dict` includes `refresh_id`, `market_version`, `stale`, and `generation` when known.
- A loader may publish a bundle only if its captured generation is still current for that market.

- [ ] **Step 1: Write a failing stale/generation test**

```python
def test_old_loader_cannot_overwrite_new_generation(monkeypatch):
    old_started = threading.Event()
    release_old = threading.Event()
    published = []

    # Arrange two controlled loaders: the old one pauses after reading data,
    # the new one completes first.
    # Assert the final cache is the new bundle and old completion is ignored.
    assert published[-1].generation == 2
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest backend/tests/test_data_cache_generation.py -q`

Expected: FAIL because the current cache has no generation guard.

- [ ] **Step 3: Add per-market generation counters and conditional publication**

Increment the market generation on invalidate. Capture it before starting the daemon thread. Before assigning `_cache[market]`, compare the captured generation with the current generation under `_lock`; discard stale results and leave the newer state untouched. Preserve existing `MarketBundle` data shape.

- [ ] **Step 4: Add explicit stale metadata without blocking reads**

When a rebuild fails and an older bundle exists, retain the bundle, set its status to `stale`, and attach the last successful `refresh_id`/market version in status. Do not report it as `loaded`/ready for the new refresh.

- [ ] **Step 5: Run focused cache and backtest cache tests**

Run: `python -m pytest backend/tests/test_data_cache_generation.py backend/tests/test_duckdb_store_hot_path.py -q`

Expected: PASS.

---

### Task 4: Expose refresh state and verify the complete contract

**Files:**
- Modify: `backend/routers/market_update.py`
- Modify: `backend/routers/backtest_cache.py` only if it needs to expose refresh metadata
- Modify: `backend/main.py` only if lifecycle recovery must run during startup
- Test: `backend/tests/test_market_refresh_api.py`
- Test: existing market updater/scheduler tests as needed

**Interfaces:**
- Add a read-only refresh status endpoint returning the active refresh and the most recent three records.
- Existing cache status responses include market version, refresh id, stale flag, and generation.
- No email delivery endpoint is added in this phase.

- [ ] **Step 1: Write failing endpoint contract tests**

Test that the endpoint returns one global `refresh_id`, three-or-fewer recent records, independent A/HK/US states, and a conflict response containing the active refresh id.

- [ ] **Step 2: Run the endpoint tests and verify failure**

Run: `python -m pytest backend/tests/test_market_refresh_api.py -q`

Expected: FAIL because the endpoint and metadata fields are not present.

- [ ] **Step 3: Implement read-only status projection and startup recovery**

At startup, mark persisted `running` records as `interrupted`; do not automatically rerun them. Keep the projection read-only with respect to update execution.

- [ ] **Step 4: Run all focused tests**

Run: `python -m pytest backend/tests/test_market_refresh_state.py backend/tests/test_market_refresh_runner.py backend/tests/test_data_cache_generation.py backend/tests/test_market_refresh_api.py backend/tests/test_scheduler_market_retry.py -q`

Expected: PASS.

- [ ] **Step 5: Run the broader market/backtest regression set**

Run: `python -m pytest backend/tests/test_market_updater_circuit_breaker.py backend/tests/test_duckdb_store_views.py backend/tests/test_duckdb_store_hot_path.py backend/tests/test_engine.py backend/tests/test_backtest_api.py -q`

Expected: PASS with no new failures.

- [ ] **Step 6: Inspect the final diff and leave unrelated worktree files untouched**

Run: `git status --short`, `git diff --stat`, and `git diff --check`. Do not include `.DS_Store`, secrets, market data, logs, or report artifacts in the commit.

---

## Explicitly Deferred

- Generic email/SMTP notification module.
- Notification retry and delivery history.
- Full point-in-time HK_CONNECT membership.
- Replacing DuckDB or Parquet.
- Rewriting all updater implementations.
- Reworking Portfolio valuation or the frontend contract; those remain separate follow-up work.

## Spec Coverage Check

- One active refresh, no queue: Tasks 1-2.
- Shared manual/scheduler lifecycle: Task 2.
- Market independence: Task 2.
- `refresh_id` plus market versions: Tasks 1-2.
- Recent three records: Task 1.
- Complete means cache ready: Tasks 2-3.
- Stale cache remains usable and explicit: Task 3.
- Generation guard: Task 3.
- Restart recovery: Task 4.
- Tests before production code: every task starts with a failing test.
- Email notifications deferred as a separate module: Explicitly Deferred.
