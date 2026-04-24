### Task 5: Router 传递 `join_modes` + `pipeline_info` 持久化

**Files:**
- Modify: `backend/routers/backtest.py:48-129`
- Modify: `backend/tests/test_backtest_api.py`

**Prerequisite:** Task 2 complete (engine accepts `join_modes`)

---

- [ ] **Step 1: Write failing tests for join_modes in API**

Append to `backend/tests/test_backtest_api.py`:

```python
class TestJoinModesAPI:
    @patch("routers.backtest._load_stock_data")
    def test_join_modes_passed_to_engine(self, mock_load):
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

        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [
                {"filepath": screener_path, "class_name": "MaCrossScreener"},
                {"filepath": screener_path, "class_name": "MaCrossScreener"},
            ],
            "join_modes": ["correlated"],
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        assert task_id

    @patch("routers.backtest._load_stock_data")
    def test_join_modes_in_pipeline_info(self, mock_load):
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

        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [
                {"filepath": screener_path, "class_name": "MaCrossScreener"},
                {"filepath": screener_path, "class_name": "MaCrossScreener"},
            ],
            "join_modes": ["correlated"],
        })
        task_id = resp.json()["task_id"]

        import time
        time.sleep(2)

        from services.backtest.task_manager import task_manager
        result = task_manager.get_result(task_id)
        assert result is not None
        pi = result.get("pipeline_info")
        assert pi is not None
        assert pi.get("join_modes") == ["correlated"]

    @patch("routers.backtest._load_stock_data")
    def test_join_modes_default_when_missing(self, mock_load):
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

        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")
        resp = client.post("/api/backtest/run", json={
            "pipeline": [
                {"filepath": screener_path, "class_name": "MaCrossScreener"},
                {"filepath": screener_path, "class_name": "MaCrossScreener"},
            ],
        })
        assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_backtest_api.py::TestJoinModesAPI -v`
Expected: FAIL — router doesn't extract `join_modes`

- [ ] **Step 3: Modify router to extract and pass `join_modes`**

In `backend/routers/backtest.py`, modify `api_run_backtest` function:

1. After `source_task_id = body.get("source_task_id")` (line 54), add:

```python
    join_modes = body.get("join_modes")
```

2. Change `pipeline_info` from a list to a dict to include `join_modes`. Replace the `pipeline_info` construction block (lines 94-109) with:

```python
    screener_infos = []
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
        screener_infos.append(info)
    pipeline_info = {"strategies": screener_infos}
    if join_modes:
        pipeline_info["join_modes"] = join_modes
```

3. Update `task_manager.create_task` call — `pipeline_info` is now a dict, not a list. The task_manager already does `json.dumps(pipeline_info)` which works for both list and dict. Update the call:

```python
    task_id = task_manager.create_task(task_type=task_type, pipeline_info=pipeline_info, start_date=start_date, end_date=end_date, source_task_id=source_task_id)
```

4. In the `run_task` inner function, pass `join_modes` to engine:

```python
    def run_task():
        try:
            task_manager.update_progress(task_id, 0, 0, "加载数据中...")
            stock_data = _load_stock_data(start_date, end_date, symbols)
            task_manager.update_progress(task_id, len(stock_data), len(stock_data), f"数据加载完成 ({len(stock_data)} 只)")
            engine = BacktestEngine(stock_data=stock_data, screeners=screeners, trader=trader, on_progress=on_progress, join_modes=join_modes)
            result = engine.run()
            result = _safe_json(result)
            task_manager.complete_task(task_id, result)
        except Exception as e:
            task_manager.fail_task(task_id, str(e))
```

- [ ] **Step 4: Update `task_manager.create_task` to accept dict pipeline_info**

In `backend/services/backtest/task_manager.py`, the `create_task` method already accepts `pipeline_info: list[dict] | None`. Update the type hint to also accept dict:

```python
    def create_task(self, task_type: str = "screener", pipeline_info: list[dict] | dict | None = None, start_date: str | None = None, end_date: str | None = None, source_task_id: str | None = None) -> str:
```

The serialization `json.dumps(pipeline_info, ensure_ascii=False)` already works for both list and dict.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_backtest_api.py::TestJoinModesAPI -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/routers/backtest.py backend/services/backtest/task_manager.py backend/tests/test_backtest_api.py
git commit -m "feat: pass join_modes from API to engine, persist in pipeline_info"
```
