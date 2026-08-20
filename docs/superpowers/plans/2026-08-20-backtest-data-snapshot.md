# Backtest Data Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为完整回测和雷达扫描增加轻量、固定且可解释的 `BacktestDataSnapshot`，不复制常驻全市场 `MarketBundle`。

**Architecture:** `data_cache` 继续拥有每个市场唯一的常驻 `MarketBundle`。新的 Snapshot module 只负责把一个 bundle 固定成 symbols、迭代窗口、数据截至日期、stale 和内部版本元信息，并把已有 `SlicedBundle` 作为引用视图交给 Engine；cache 重建不会修改已经创建的 Snapshot。回测结果对用户展示 `data_as_of` 和 stale，refresh_id 仅作为内部诊断字段。

**Tech Stack:** Python 3.10, dataclasses, pandas, DuckDB, FastAPI, pytest, pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-08-20-backtest-data-snapshot-design.md`

## Global Constraints

- 生产仍按 A/HK/US 市场完整预加载，禁止改成逐股票或分批生产加载。
- Snapshot 不深拷贝全市场 DataFrame；只复用 `MarketBundle` 和 `SlicedBundle` 的数据引用。
- DuckDB 是业务数据唯一查询入口，测试使用临时 Parquet + 真实 DuckDB mini fixture。
- stale 数据允许用于回测和雷达，但结果必须显式标记 stale。
- `refresh_id` 不作为用户操作概念；第一阶段不实现 fingerprint 或历史版本选择。
- 不恢复 StrategyGroup、Screener/Buyer/Seller 三角模型。
- 遵守 TDD：每个生产行为先写一个会失败的测试，再实现最小代码。

---

### Task 1: Define Snapshot Module

**Files:**
- Create: `backend/services/backtest/data_snapshot.py`
- Modify: `backend/services/backtest/data_cache.py` only if a small public metadata helper is required
- Test: `backend/tests/test_data_snapshot.py`

**Interfaces:**
- Consumes: `MarketBundle`, `SlicedBundle`, `data_cache.get_status()`, `data_cache.get_generation()` and existing `slice_bundle()`.
- Produces:
  - `BacktestDataSnapshot` frozen dataclass.
  - `create_snapshot(bundle, market, symbols, start_date, end_date, *, refresh_id=None, market_version=None, stale=None) -> BacktestDataSnapshot`.
  - `BacktestDataSnapshot.sliced -> SlicedBundle`.
  - `BacktestDataSnapshot.data_context() -> dict`.

- [ ] **Step 1: Write the failing tests**

  Add tests that construct a small `MarketBundle` with two DataFrames and verify:

  ```python
  def test_snapshot_reuses_bundle_dataframes():
      snapshot = create_snapshot(bundle, "A", ["000001.SZ"], "2020-01-01", "2020-12-31")
      assert snapshot.sliced.stock_data["000001.SZ"] is bundle.stock_data["000001.SZ"]
  
  def test_snapshot_contains_user_facing_data_context():
      snapshot = create_snapshot(
          bundle, "A", None, None, None,
          refresh_id="r1", market_version=4, stale=True,
      )
      assert snapshot.data_context() == {
          "market": "A",
          "data_as_of": bundle.last_date,
          "stale": True,
      }
  ```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

  Run:

  ```bash
  python -m pytest backend/tests/test_data_snapshot.py -q
  ```

  Expected: collection or assertion failure because `data_snapshot.py` and `create_snapshot()` do not exist yet.

- [ ] **Step 3: Implement the minimal Snapshot module**

  Use a frozen dataclass with these fields:

  ```python
  @dataclass(frozen=True)
  class BacktestDataSnapshot:
      market: str
      bundle: MarketBundle
      sliced: SlicedBundle
      symbols: tuple[str, ...]
      start_date: str | None
      end_date: str | None
      data_as_of: str | None
      stale: bool
      generation: int
      market_version: int | None
      refresh_id: str | None
  ```

  `create_snapshot()` must call the existing `slice_bundle()` and must not copy DataFrames. If `bundle` is `None` or the sliced stock data is empty, raise `ValueError` with an actionable message. `data_context()` returns only `market`, `data_as_of`, and `stale`; internal fields remain available on the object for later result serialization.

- [ ] **Step 4: Run the focused tests and verify they pass**

  Run the same command. Expected: all Snapshot tests pass.

- [ ] **Step 5: Run the existing cache generation tests**

  ```bash
  python -m pytest backend/tests/test_data_cache_generation.py -q
  ```

  Expected: existing generation guard tests remain green.

### Task 2: Make Engine Consume a Snapshot Without Breaking Strategy Semantics

**Files:**
- Modify: `backend/services/backtest/engine.py`
- Modify: `backend/services/backtest/market_data.py` only for type/metadata access if needed
- Modify: `backend/services/backtest/context.py` only if Snapshot metadata must be exposed to strategies
- Test: `backend/tests/test_data_snapshot.py`, `backend/tests/test_engine.py`

**Interfaces:**
- Consumes: `BacktestDataSnapshot` from Task 1.
- Produces: `BacktestEngine(strategy=..., snapshot=..., ...)` as the preferred construction path; the existing execution order, Strategy hooks, broker rules, and `run()`/`run_scan()` outputs remain unchanged.

- [ ] **Step 1: Write failing engine tests**

  Add tests that instantiate the Engine with a Snapshot and assert:

  ```python
  def test_engine_accepts_snapshot_and_preserves_iteration_window(snapshot, strategy):
      engine = BacktestEngine(strategy=strategy, snapshot=snapshot)
      assert engine._iter_start <= engine._iter_end
  
  def test_engine_result_contains_data_context(snapshot, strategy):
      result = BacktestEngine(strategy=strategy, snapshot=snapshot).run()
      assert result["data_context"]["data_as_of"] == snapshot.data_as_of
      assert result["data_context"]["stale"] is snapshot.stale
  ```

- [ ] **Step 2: Run the focused tests and verify they fail for the new construction path**

  ```bash
  python -m pytest backend/tests/test_data_snapshot.py backend/tests/test_engine.py -q
  ```

  Expected: failure because `BacktestEngine` does not yet accept `snapshot` and results do not yet serialize `data_context`.

- [ ] **Step 3: Add the Snapshot construction path**

  Let `BacktestEngine.__init__` accept `snapshot: BacktestDataSnapshot | None = None`. When supplied, derive the existing Engine inputs from `snapshot.sliced` and set `self._data_snapshot`. Keep the current execution loop and `MarketData` construction unchanged. Do not deep-copy the bundle or alter Strategy behavior.

- [ ] **Step 4: Add result metadata at the single result assembly point**

  Add `data_context` from `self._data_snapshot.data_context()` to both complete backtest and scan result payloads. Keep `refresh_id`, `generation`, and `market_version` in a separate internal `data_provenance` object only if the existing result schema has a stable place for it; otherwise expose them in the task result JSON without changing front-end display fields.

- [ ] **Step 5: Run focused Engine tests and the existing Engine suite**

  ```bash
  python -m pytest backend/tests/test_data_snapshot.py backend/tests/test_engine.py backend/tests/test_engine_e2e.py -q
  ```

  Expected: all selected tests pass using the mini fixture and no project `data/market` access.

### Task 3: Route Backtest and Radar Through Snapshot Creation

**Files:**
- Modify: `backend/routers/backtest.py`
- Modify: `backend/routers/screener.py` only if the current screener path can consume the same Snapshot without broadening its existing A-only contract
- Modify: `backend/services/backtest/market_filter.py` only to pass the already-resolved market/symbol set, not to change HK_CONNECT semantics
- Test: `backend/tests/test_backtest_api.py`, `backend/tests/test_screener_api.py`, `backend/tests/test_data_snapshot.py`

**Interfaces:**
- Consumes: `data_cache.get_market()`, `data_cache.get_status()`, `data_cache.get_generation()`, `apply_market_filter()`, and `create_snapshot()`.
- Produces: both `/api/backtest/run` and `/api/backtest/scan-radar` construct one Snapshot before starting their daemon task; cache-not-loaded remains an explicit error.

- [ ] **Step 1: Write failing route tests**

  Add tests using the existing mini fixture and patched cache that verify:

  - a backtest task receives the selected market and filtered symbols through Snapshot;
  - a scan result includes `data_context.data_as_of` and `data_context.stale`;
  - a missing bundle returns the current actionable “load data first” failure rather than triggering hidden IO;
  - `HK_CONNECT` still maps to HK and its current symbol filter is unchanged.

- [ ] **Step 2: Run the route tests to verify the new assertions fail**

  ```bash
  python -m pytest backend/tests/test_backtest_api.py backend/tests/test_screener_api.py -q
  ```

  Expected: failure because route code still calls `slice_bundle()` and constructs Engine directly without Snapshot metadata.

- [ ] **Step 3: Create Snapshot in the backtest route**

  In `run_task()`, resolve the bundle once, read the current cache status, and call:

  ```python
  snapshot = create_snapshot(
      bundle,
      data_market,
      target_symbols,
      start_date,
      end_date,
      refresh_id=status.get("refresh_id"),
      market_version=status.get("market_version"),
      stale=status.get("stale", False),
  )
  engine = BacktestEngine(strategy=strategy, snapshot=snapshot, ...)
  ```

  The route must not call `load_market_async()` in the backtest task. Existing explicit cache loading behavior remains unchanged.

- [ ] **Step 4: Route radar through the same path**

  Replace its direct `slice_bundle()`/Engine data wiring with the same Snapshot factory. Keep lookback date resolution and `run_scan()` behavior unchanged.

- [ ] **Step 5: Decide screener scope from actual call sites**

  If `/api/screener/run` can use the same loaded A-market bundle without changing its current API contract, migrate it to Snapshot. If it still intentionally performs its separate A-only screen path, add only a test/documentation note and do not introduce a forced refactor in this task.

- [ ] **Step 6: Run focused route tests**

  ```bash
  python -m pytest backend/tests/test_backtest_api.py backend/tests/test_screener_api.py backend/tests/test_data_snapshot.py -q
  ```

  Expected: all selected tests pass and no test reads the repository `data/market` directory.

### Task 4: Add Stale/Generation Regression Coverage and Verify the Full Contract

**Files:**
- Modify: `backend/tests/test_data_cache_generation.py`
- Modify: `backend/tests/test_engine.py`
- Modify: `backend/tests/test_engine_e2e.py`
- Modify: `backend/tests/test_backtest_api.py`
- Modify: `backend/tests/agent/test_routes_agent.py` only if the shared result contract is asserted there
- No production file changes unless a focused test exposes a contract bug from Tasks 1-3

**Interfaces:**
- Consumes: the completed Snapshot factory, Engine construction path, and route result metadata.
- Produces: regression evidence that Snapshot is stable across cache invalidation and user-facing metadata stays simple.

- [ ] **Step 1: Add the cache replacement regression test**

  Create an old Snapshot, call `data_cache.invalidate("A")`, install a new bundle/generation, and assert the old Snapshot still points to the original DataFrame while a new Snapshot reports the new generation and `data_as_of`.

- [ ] **Step 2: Add stale-result regression coverage**

  Construct a Snapshot with `stale=True`, run the smallest supported Engine path, and assert the result carries `data_context.stale is True` without rejecting the run.

- [ ] **Step 3: Run the complete backend suite in one controlled process**

  Use the project Python 3.10 environment and the existing mini-market fixture. Run:

  ```bash
  PYTHONPATH=".:backend:.venv/lib/python3.10/site-packages" \
  .venv/bin/python -m pytest backend/tests/ -q
  ```

  Expected: zero failures; any skipped test must have an explicit existing reason. Do not run concurrent pytest processes or start the production full-market preload during this verification.

- [ ] **Step 4: Run static checks and inspect scope**

  ```bash
  git diff --check
  git status --short
  ```

  Confirm that only Snapshot, backtest wiring, tests, and the plan/spec changed; no `data/`, `report/`, `logs/`, secrets, or generated full-market files are staged.

- [ ] **Step 5: Commit the implementation after verification**

  ```bash
  git add backend/services/backtest/data_snapshot.py \
    backend/services/backtest/data_cache.py \
    backend/services/backtest/engine.py \
    backend/services/backtest/market_data.py \
    backend/services/backtest/context.py \
    backend/routers/backtest.py \
    backend/routers/screener.py \
    backend/services/backtest/market_filter.py \
    backend/tests/test_data_snapshot.py \
    backend/tests/test_engine.py \
    backend/tests/test_engine_e2e.py \
    backend/tests/test_backtest_api.py \
    backend/tests/test_screener_api.py \
    docs/superpowers/specs/2026-08-20-backtest-data-snapshot-design.md \
    docs/superpowers/plans/2026-08-20-backtest-data-snapshot.md
  git commit -m "feat(backtest): add stable data snapshot context"
  ```
