# 链式回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow using a previous screener task's results (stock pool) as input to a new backtest, avoiding re-running the previous strategy.

**Architecture:** Add `source_task_id` optional field to `POST /api/backtest/run`. Backend resolves the source task's screened symbols, filters `_load_stock_data()` to only those symbols, and inherits the source task's date range. Frontend adds a button on `BacktestResult.vue` to chain, and `BacktestPage.vue` displays source info when chaining.

**Tech Stack:** Python/FastAPI backend, Vue 3 frontend, SQLite persistence

---

### Task 1: Add `source_task_id` column to `backtest_tasks` table

**Files:**
- Modify: `backend/services/backtest/task_manager.py:16-40` (`_init_table`)
- Modify: `backend/services/backtest/task_manager.py:51-65` (`create_task`)
- Modify: `backend/services/backtest/task_manager.py:134-161` (`get_result`)
- Modify: `backend/services/backtest/task_manager.py:163-185` (`list_tasks`)
- Test: `backend/tests/test_backtest_api.py`

- [ ] **Step 1: Write failing test for source_task_id persistence**

In `backend/tests/test_backtest_api.py`, add at the end of the file:

```python
class TestTaskManagerSourceTask:
    def setup_method(self):
        from services.backtest.task_manager import TaskManager
        self.tm = TaskManager()

    def test_create_task_with_source_task_id(self):
        tid = self.tm.create_task(
            task_type="screener",
            source_task_id="src123",
        )
        result = self.tm.get_result(tid)
        assert result["source_task_id"] == "src123"

    def test_create_task_without_source_task_id(self):
        tid = self.tm.create_task(task_type="screener")
        result = self.tm.get_result(tid)
        assert result.get("source_task_id") is None

    def test_list_tasks_includes_source_task_id(self):
        tid = self.tm.create_task(
            task_type="screener",
            source_task_id="src456",
        )
        tasks = self.tm.list_tasks()
        task = next(t for t in tasks if t["task_id"] == tid)
        assert task["source_task_id"] == "src456"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_backtest_api.py::TestTaskManagerSourceTask -v`
Expected: FAIL — `create_task()` does not accept `source_task_id`

- [ ] **Step 3: Implement source_task_id in task_manager.py**

In `backend/services/backtest/task_manager.py`:

1. In `_init_table()`, add migration for the new column (line 33, append to the list):

```python
for col, typedef in [("task_type", "TEXT NOT NULL DEFAULT 'screener'"), ("summary", "TEXT"), ("pipeline_info", "TEXT"), ("start_date", "TEXT"), ("end_date", "TEXT"), ("source_task_id", "TEXT")]:
```

2. In `create_task()` (line 51), add `source_task_id` parameter and persist it:

```python
def create_task(self, task_type: str = "screener", pipeline_info: list[dict] | None = None, start_date: str | None = None, end_date: str | None = None, source_task_id: str | None = None) -> str:
    task_id = str(uuid.uuid4())[:8]
    pi_json = json.dumps(pipeline_info, ensure_ascii=False) if pipeline_info else None
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, start_date, end_date, source_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, "running", task_type, pi_json, start_date, end_date, source_task_id, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    with self._lock:
        self._progress[task_id] = None
    return task_id
```

3. In `get_result()` (line 134), add `source_task_id` to SELECT and response:

```python
def get_result(self, task_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT status, result, error, pipeline_info, start_date, end_date, source_task_id FROM backtest_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    result = json.loads(row["result"]) if row["result"] else None
    resp = {
        "task_id": task_id,
        "status": row["status"],
        "result": result,
        "error": row["error"],
    }
    if row["pipeline_info"]:
        try:
            resp["pipeline_info"] = json.loads(row["pipeline_info"])
        except Exception:
            pass
    if row["start_date"]:
        resp["start_date"] = row["start_date"]
    if row["end_date"]:
        resp["end_date"] = row["end_date"]
    if row["source_task_id"]:
        resp["source_task_id"] = row["source_task_id"]
    return resp
```

4. In `list_tasks()` (line 163), add `source_task_id` to SELECT and response:

```python
def list_tasks(self) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT task_id, status, task_type, summary, created_at, source_task_id FROM backtest_tasks ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    result = []
    for r in rows:
        item = {
            "task_id": r["task_id"],
            "status": r["status"],
            "task_type": r["task_type"],
            "created_at": r["created_at"],
        }
        if r["source_task_id"]:
            item["source_task_id"] = r["source_task_id"]
        if r["summary"]:
            try:
                item["summary"] = json.loads(r["summary"])
            except Exception:
                pass
        result.append(item)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_backtest_api.py::TestTaskManagerSourceTask -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/task_manager.py backend/tests/test_backtest_api.py
git commit -m "feat: add source_task_id column to backtest_tasks"
```

---

### Task 2: Add `symbols` filter to `_load_stock_data()` and `source_task_id` logic in router

**Files:**
- Modify: `backend/routers/backtest.py:40-102` (`api_run_backtest`)
- Modify: `backend/routers/backtest.py:126-137` (`_load_stock_data`)
- Test: `backend/tests/test_backtest_api.py`

- [ ] **Step 1: Write failing tests for source_task_id in API**

In `backend/tests/test_backtest_api.py`, add at the end:

```python
class TestChainBacktest:
    def setup_method(self):
        from services.backtest.task_manager import task_manager
        self.tm = task_manager

    def test_source_task_not_found(self):
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
            "source_task_id": "nonexistent",
        })
        assert resp.status_code == 400
        assert "不存在" in resp.json()["detail"]

    def test_source_task_not_success(self):
        tid = self.tm.create_task(task_type="screener")
        self.tm.fail_task(tid, "test error")
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
            "source_task_id": tid,
        })
        assert resp.status_code == 400
        assert "未成功" in resp.json()["detail"]

    def test_source_task_no_screened_symbols(self):
        tid = self.tm.create_task(task_type="backtest")
        self.tm.complete_task(tid, {"metrics": {"total_return": 0.1}})
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
            "source_task_id": tid,
        })
        assert resp.status_code == 400
        assert "选股" in resp.json()["detail"]

    def test_source_task_empty_symbols(self):
        tid = self.tm.create_task(task_type="screener")
        self.tm.complete_task(tid, {"screened_symbols": []})
        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
            "source_task_id": tid,
        })
        assert resp.status_code == 400
        assert "未选出" in resp.json()["detail"]

    @patch("routers.backtest._load_stock_data")
    def test_chain_backtest_passes_symbols_and_dates(self, mock_load):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"000001": df}

        src_tid = self.tm.create_task(
            task_type="screener",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        self.tm.complete_task(src_tid, {
            "screened_symbols": [
                {"symbol": "000001", "match_dates": ["2024-02-01"]},
                {"symbol": "600036", "match_dates": ["2024-03-01"]},
            ]
        })

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
            "source_task_id": src_tid,
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()

        mock_load.assert_called_once_with("2024-01-01", "2024-12-31", ["000001", "600036"])

    @patch("routers.backtest._load_stock_data")
    def test_chain_backtest_flat_symbol_list(self, mock_load):
        import pandas as pd
        import numpy as np
        n = 30
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        mock_load.return_value = {"000001": df}

        src_tid = self.tm.create_task(task_type="screener")
        self.tm.complete_task(src_tid, {
            "screened_symbols": ["000001", "600036"]
        })

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
            "source_task_id": src_tid,
        })
        assert resp.status_code == 200
        mock_load.assert_called_once_with(None, None, ["000001", "600036"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_backtest_api.py::TestChainBacktest -v`
Expected: FAIL — router doesn't handle `source_task_id`

- [ ] **Step 3: Implement source_task_id logic in router**

In `backend/routers/backtest.py`:

1. Add `_extract_symbols` helper after `_safe_json` (after line 31):

```python
def _extract_symbols(screened_symbols: list) -> list[str]:
    if not screened_symbols:
        return []
    if isinstance(screened_symbols[0], str):
        return list(screened_symbols)
    return [item["symbol"] for item in screened_symbols]
```

2. Replace `api_run_backtest` function (lines 40-102) with version that handles `source_task_id`:

```python
@router.post("/run")
def api_run_backtest(body: dict = Body(...)):
    pipeline = body.get("pipeline", [])
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    param_overrides = body.get("param_overrides", {})
    source_task_id = body.get("source_task_id")

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

    symbols = None
    if source_task_id:
        source = task_manager.get_result(source_task_id)
        if source is None:
            raise HTTPException(status_code=400, detail="来源任务不存在")
        if source["status"] != "success":
            raise HTTPException(status_code=400, detail="来源任务未成功完成")
        source_result = source.get("result") or {}
        if "screened_symbols" not in source_result:
            raise HTTPException(status_code=400, detail="来源任务不是选股类型")
        symbols = _extract_symbols(source_result["screened_symbols"])
        if not symbols:
            raise HTTPException(status_code=400, detail="来源任务未选出任何股票")
        start_date = source.get("start_date")
        end_date = source.get("end_date")

    screeners = []
    trader = None
    for item in pipeline:
        filepath = Path(item["filepath"])
        class_name = item["class_name"]
        overrides = param_overrides.get(class_name, {})
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == class_name), None)
        if cls is None:
            raise HTTPException(status_code=400, detail=f"Strategy class {class_name} not found in {filepath}")
        instance = cls(param_overrides=overrides)
        if isinstance(instance, TraderStrategy):
            trader = instance
        elif isinstance(instance, ScreenerStrategy):
            screeners.append(instance)

    task_type = "backtest" if trader else "screener"
    pipeline_info = []
    for item in pipeline:
        cls_name = item["class_name"]
        overrides = param_overrides.get(cls_name, {})
        classes = load_strategy_from_file(Path(item["filepath"]))
        cls = next((c for c in classes if c.__name__ == cls_name), None)
        info = {"class_name": cls_name}
        if cls:
            info["name"] = getattr(cls, "name", cls_name)
            info["strategy_type"] = getattr(cls, "strategy_type", "")
            if hasattr(cls, "frequency"):
                info["frequency"] = cls.frequency
            defaults = {k: v["default"] for k, v in getattr(cls, "params", {}).items()}
            merged = {**defaults, **overrides}
            info["params"] = merged
        pipeline_info.append(info)
    task_id = task_manager.create_task(task_type=task_type, pipeline_info=pipeline_info, start_date=start_date, end_date=end_date, source_task_id=source_task_id)

    def on_progress(current, total, phase):
        task_manager.update_progress(task_id, current, total, phase)

    def run_task():
        try:
            task_manager.update_progress(task_id, 0, 0, "加载数据中...")
            stock_data = _load_stock_data(start_date, end_date, symbols)
            task_manager.update_progress(task_id, len(stock_data), len(stock_data), f"数据加载完成 ({len(stock_data)} 只)")
            engine = BacktestEngine(stock_data=stock_data, screeners=screeners, trader=trader, on_progress=on_progress)
            result = engine.run()
            result = _safe_json(result)
            task_manager.complete_task(task_id, result)
        except Exception as e:
            task_manager.fail_task(task_id, str(e))

    t = threading.Thread(target=run_task, daemon=True)
    t.start()
    return {"task_id": task_id, "status": "running"}
```

3. Update `_load_stock_data` (lines 126-137) to accept `symbols` parameter:

```python
def _load_stock_data(start_date: str = None, end_date: str = None, symbols: list[str] = None) -> dict[str, pd.DataFrame]:
    stock_data = {}
    if symbols is not None:
        filepaths = [QFQ_KLINE_DIR / f"{s}.parquet" for s in symbols]
        filepaths = [f for f in filepaths if f.exists()]
    else:
        filepaths = list(QFQ_KLINE_DIR.glob("*.parquet"))
    for filepath in filepaths:
        symbol = filepath.stem
        df = pd.read_parquet(filepath)
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        if not df.empty:
            stock_data[symbol] = df
    return stock_data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_backtest_api.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All 168+ tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/backtest.py backend/tests/test_backtest_api.py
git commit -m "feat: support source_task_id in backtest API for chain backtest"
```

---

### Task 3: Add "以此结果进行下一步回测" button to BacktestResult.vue

**Files:**
- Modify: `frontend/src/views/BacktestResult.vue`

- [ ] **Step 1: Add the chain button and source task link**

In `frontend/src/views/BacktestResult.vue`:

1. Add `sourceTaskId` ref and load it in `onMounted` (in `<script setup>`, after line 85):

```javascript
const sourceTaskId = ref(null)
```

In the `onMounted` callback, after `pipelineInfo.value = data.pipeline_info || null` (line 90), add:

```javascript
sourceTaskId.value = data.source_task_id || null
```

2. Add source task info display and chain button in `<template>`. After the closing `</div>` of `pipeline-info` block (after line 19), add:

```html
<div v-if="sourceTaskId" class="source-info">
  来源任务:
  <span class="source-link" @click="$router.push('/backtest/result/' + sourceTaskId)">{{ sourceTaskId }}</span>
</div>
```

After the screener result table closing `</div>` (after line 41, before the `v-else-if="result"` block), add:

```html
<div v-if="result && result.screened_symbols && result.screened_symbols.length" class="chain-actions">
  <button class="btn-chain" @click="$router.push({ path: '/backtest', query: { source_task_id: taskId } })">以此结果进行下一步回测</button>
</div>
```

3. Add styles (append to `<style scoped>`):

```css
.source-info { font-size: 13px; color: #606266; margin-bottom: 12px; }
.source-link { color: #409eff; cursor: pointer; }
.source-link:hover { text-decoration: underline; }
.chain-actions { margin-top: 16px; }
.btn-chain { background: #409eff; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-chain:hover { background: #66b1ff; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/BacktestResult.vue
git commit -m "feat: add chain backtest button on screener result page"
```

---

### Task 4: Handle `source_task_id` in BacktestPage.vue

**Files:**
- Modify: `frontend/src/views/BacktestPage.vue`
- Modify: `frontend/src/api/index.js` (no change needed — `runBacktest` already passes body through)

- [ ] **Step 1: Add source task handling to BacktestPage.vue**

In `frontend/src/views/BacktestPage.vue`:

1. Add imports and refs. In `<script setup>` (line 50), update imports:

```javascript
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchStrategies, runBacktest, fetchBacktestStatus, fetchBacktestTasks, fetchBacktestResult } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'
import ParamEditor from '../components/ParamEditor.vue'

const route = useRoute()
```

2. Add source-related refs (after `const progress = ref(null)` on line 64):

```javascript
const sourceTaskId = ref(null)
const sourceInfo = ref(null)
```

3. Update `onMounted` (lines 128-132) to load source task info:

```javascript
onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
  loadTasks()
  const srcId = route.query.source_task_id
  if (srcId) {
    try {
      const { data: srcData } = await fetchBacktestResult(srcId)
      if (srcData.status === 'success' && srcData.result && srcData.result.screened_symbols) {
        sourceTaskId.value = srcId
        const syms = srcData.result.screened_symbols
        const count = Array.isArray(syms) ? syms.length : 0
        sourceInfo.value = {
          count,
          start_date: srcData.start_date,
          end_date: srcData.end_date,
        }
        if (srcData.start_date) startDate.value = srcData.start_date
        if (srcData.end_date) endDate.value = srcData.end_date
      }
    } catch {}
  }
})
```

4. Update `runBacktestPipeline` (lines 93-106) to include `source_task_id`:

```javascript
async function runBacktestPipeline() {
  running.value = true
  progress.value = null
  const body = {
    pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
    param_overrides: overrides.value,
  }
  if (sourceTaskId.value) {
    body.source_task_id = sourceTaskId.value
  } else {
    if (startDate.value) body.start_date = startDate.value
    if (endDate.value) body.end_date = endDate.value
  }
  const { data } = await runBacktest(body)
  taskId.value = data.task_id
  status.value = 'running'
  pollTimer = setInterval(pollStatus, 2000)
}
```

5. Add `clearSource` function (after `runBacktestPipeline`):

```javascript
function clearSource() {
  sourceTaskId.value = null
  sourceInfo.value = null
  startDate.value = ''
  endDate.value = ''
}
```

6. Update `<template>`. After `<h1>回测</h1>` (line 3), add source info card:

```html
<div v-if="sourceInfo" class="source-card">
  <div class="source-card-content">
    <span>基于任务 <b>{{ sourceTaskId }}</b> 的选股结果（{{ sourceInfo.count }} 只股票）</span>
    <span v-if="sourceInfo.start_date || sourceInfo.end_date" class="source-dates">
      ，日期范围 {{ sourceInfo.start_date || '最早' }} ~ {{ sourceInfo.end_date || '最新' }}
    </span>
  </div>
  <button class="btn-clear-source" @click="clearSource">清除来源</button>
</div>
```

7. Update date inputs to be disabled when source is active. Replace the `date-range` div (lines 6-9):

```html
<div class="date-range">
  <label>开始日期: <input v-model="startDate" type="date" :disabled="!!sourceInfo" /></label>
  <label>结束日期: <input v-model="endDate" type="date" :disabled="!!sourceInfo" /></label>
</div>
```

8. Add styles (append to `<style scoped>`):

```css
.source-card { display: flex; align-items: center; justify-content: space-between; background: #ecf5ff; border: 1px solid #b3d8ff; border-radius: 6px; padding: 12px 16px; margin-bottom: 16px; }
.source-card-content { font-size: 14px; color: #303133; }
.source-dates { color: #606266; }
.btn-clear-source { background: transparent; border: 1px solid #dcdfe6; color: #606266; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-clear-source:hover { border-color: #409eff; color: #409eff; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/BacktestPage.vue
git commit -m "feat: handle source_task_id in BacktestPage for chain backtest"
```

---

### Task 5: Run full test suite and verify

**Files:** None (verification only)

- [ ] **Step 1: Run full backend test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All tests PASS (170+)

- [ ] **Step 2: Commit any remaining changes**

If all tests pass, no additional commit needed. If any tests fail, fix and commit.
