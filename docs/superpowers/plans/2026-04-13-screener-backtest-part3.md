# Part 3: Backend API + K-line Adjust (Tasks 7-9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

---

## Task 7: Task Manager + Backtest Router

**Files:**
- Create: `backend/services/backtest/task_manager.py`
- Create: `backend/routers/backtest.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_backtest_api.py`

### Steps

- [ ] **Step 1: Implement TaskManager**

Create `backend/services/backtest/task_manager.py`:

```python
import threading
import uuid
from datetime import datetime


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_task(self) -> str:
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._tasks[task_id] = {
                "status": "running",
                "result": None,
                "error": None,
                "created_at": datetime.now().isoformat(),
            }
        return task_id

    def complete_task(self, task_id: str, result: dict):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "success"
                self._tasks[task_id]["result"] = result

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "failed"
                self._tasks[task_id]["error"] = error

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {"task_id": task_id, "status": task["status"]}

    def get_result(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task_id,
                "status": task["status"],
                "result": task["result"],
                "error": task["error"],
            }

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [
                {"task_id": tid, "status": t["status"], "created_at": t["created_at"]}
                for tid, t in sorted(self._tasks.items(), key=lambda x: x[1]["created_at"], reverse=True)
            ]


task_manager = TaskManager()
```

- [ ] **Step 2: Implement backtest router**

Create `backend/routers/backtest.py`:

```python
import json
import math
import threading
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body

from config import QFQ_KLINE_DIR, STRATEGY_DIR
from services.backtest.strategy_loader import scan_strategies, load_strategy_from_file
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.task_manager import task_manager


router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _safe_json(obj):
    def _clean(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    def _clean_obj(o):
        if isinstance(o, dict):
            return {k: _clean_obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_clean_obj(i) for i in o]
        return _clean(o)

    return _clean_obj(obj)


@router.get("/strategies")
def api_list_strategies():
    if not STRATEGY_DIR.exists():
        return []
    return scan_strategies(STRATEGY_DIR)


@router.post("/run")
def api_run_backtest(body: dict = Body(...)):
    pipeline = body.get("pipeline", [])
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    param_overrides = body.get("param_overrides", {})

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

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

    task_id = task_manager.create_task()

    def run_task():
        try:
            stock_data = _load_stock_data(start_date, end_date)
            engine = BacktestEngine(stock_data=stock_data, screeners=screeners, trader=trader)
            result = engine.run()
            result = _safe_json(result)
            task_manager.complete_task(task_id, result)
        except Exception as e:
            task_manager.fail_task(task_id, str(e))

    t = threading.Thread(target=run_task, daemon=True)
    t.start()
    return {"task_id": task_id, "status": "running"}


@router.get("/status/{task_id}")
def api_backtest_status(task_id: str):
    status = task_manager.get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@router.get("/result/{task_id}")
def api_backtest_result(task_id: str):
    result = task_manager.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


def _load_stock_data(start_date: str = None, end_date: str = None) -> dict[str, pd.DataFrame]:
    stock_data = {}
    for filepath in QFQ_KLINE_DIR.glob("*.parquet"):
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

- [ ] **Step 3: Register router in main.py**

Add to `backend/main.py` after the existing router imports:

```python
from routers.backtest import router as backtest_router
```

And add after `app.include_router(data_update_router)`:

```python
app.include_router(backtest_router)
```

- [ ] **Step 4: Write tests for backtest API**

Create `backend/tests/test_backtest_api.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestBacktestStrategies:
    def test_list_strategies(self):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_strategies_have_correct_fields(self):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        data = resp.json()
        if data:
            s = data[0]
            assert "name" in s
            assert "strategy_type" in s
            assert "params" in s
            assert "filepath" in s


class TestBacktestRun:
    def test_empty_pipeline_returns_400(self):
        resp = client.post("/api/backtest/run", json={"pipeline": []})
        assert resp.status_code == 400

    @patch("routers.backtest._load_stock_data")
    def test_run_returns_task_id(self, mock_load):
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
        mock_load.return_value = {"TEST.SH": df}

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")

        resp = client.post("/api/backtest/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()


class TestBacktestStatus:
    def test_nonexistent_task(self):
        resp = client.get("/api/backtest/status/nonexistent")
        assert resp.status_code == 404

    def test_nonexistent_result(self):
        resp = client.get("/api/backtest/result/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_backtest_api.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/task_manager.py backend/routers/backtest.py backend/main.py backend/tests/test_backtest_api.py
git commit -m "feat: backtest REST API with async task manager"
```

---

## Task 8: Screener Router

**Files:**
- Create: `backend/routers/screener.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_screener_api.py`

### Steps

- [ ] **Step 1: Implement screener router**

Create `backend/routers/screener.py`:

```python
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body

from config import QFQ_KLINE_DIR, STRATEGY_DIR
from services.backtest.strategy_loader import load_strategy_from_file
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy


router = APIRouter(prefix="/api/screener", tags=["screener"])

_latest_result: dict | None = None


@router.post("/run")
def api_run_screener(body: dict = Body(...)):
    global _latest_result
    pipeline = body.get("pipeline", [])
    param_overrides = body.get("param_overrides", {})

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

    screeners = []
    for item in pipeline:
        filepath = Path(item["filepath"])
        class_name = item["class_name"]
        overrides = param_overrides.get(class_name, {})
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == class_name), None)
        if cls is None:
            raise HTTPException(status_code=400, detail=f"Strategy class {class_name} not found")
        instance = cls(param_overrides=overrides)
        if not isinstance(instance, ScreenerStrategy):
            raise HTTPException(status_code=400, detail=f"{class_name} is not a ScreenerStrategy")
        screeners.append(instance)

    stock_data = {}
    for filepath in QFQ_KLINE_DIR.glob("*.parquet"):
        symbol = filepath.stem
        df = pd.read_parquet(filepath)
        if not df.empty:
            stock_data[symbol] = df

    engine = BacktestEngine(stock_data=stock_data, screeners=screeners, trader=None)
    result = engine.run()

    _latest_result = {
        "screened_symbols": result["screened_symbols"],
        "count": len(result["screened_symbols"]),
        "pipeline": [item["class_name"] for item in pipeline],
    }
    return _latest_result


@router.get("/result")
def api_get_screener_result():
    if _latest_result is None:
        return {"screened_symbols": [], "count": 0, "pipeline": []}
    return _latest_result
```

- [ ] **Step 2: Register screener router in main.py**

Add to `backend/main.py` after backtest router import:

```python
from routers.screener import router as screener_router
```

And add:

```python
app.include_router(screener_router)
```

- [ ] **Step 3: Write tests for screener API**

Create `backend/tests/test_screener_api.py`:

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import pandas as pd
import numpy as np

from main import app

client = TestClient(app)


class TestScreenerRoutes:
    def test_empty_pipeline_returns_400(self):
        resp = client.post("/api/screener/run", json={"pipeline": []})
        assert resp.status_code == 400

    def test_get_result_initially_empty(self):
        resp = client.get("/api/screener/result")
        assert resp.status_code == 200
        data = resp.json()
        assert "screened_symbols" in data

    @patch("routers.screener.QFQ_KLINE_DIR")
    def test_run_screener_with_mock_data(self, mock_dir, tmp_path):
        n = 60
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist(),
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": [1e6] * n, "amount": [1e7] * n,
        })
        pq_path = tmp_path / "TEST.SH.parquet"
        df.to_parquet(pq_path)
        mock_dir.glob = tmp_path.glob

        from pathlib import Path
        strategies_dir = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"
        screener_path = str(strategies_dir / "ma_cross_screener.py")

        resp = client.post("/api/screener/run", json={
            "pipeline": [{"filepath": screener_path, "class_name": "MaCrossScreener"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "screened_symbols" in data
        assert "count" in data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_screener_api.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/screener.py backend/main.py backend/tests/test_screener_api.py
git commit -m "feat: screener REST API for stock screening pipeline"
```

---

## Task 9: K-line Adjust Parameter (不复权/前复权 toggle)

**Files:**
- Modify: `backend/routers/stock.py`
- Modify: `backend/config.py` (already done in Task 1)
- Test: `backend/tests/test_api.py` (add new test)

### Steps

- [ ] **Step 1: Modify stock router to support adjust parameter**

In `backend/routers/stock.py`, update the kline endpoint to accept an `adjust` parameter:

Change the `api_get_kline` function: replace the `filepath` line to use `adjust` parameter:

```python
@router.get("/{symbol}/kline")
def api_get_kline(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    period: str = Query("daily", description="daily/weekly/monthly"),
    adjust: str = Query("raw", description="raw/qfq"),
):
    from config import QFQ_KLINE_DIR
    data_dir = QFQ_KLINE_DIR if adjust == "qfq" else RAW_KLINE_DIR
    filepath = data_dir / f"{symbol}.parquet"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    df = get_kline(filepath, start_date=start_date, end_date=end_date)
    if period in ("weekly", "monthly"):
        df = aggregate_kline(df, period=period)
    return df.to_dict(orient="records")
```

Do the same for `api_get_indicators`:

```python
@router.get("/{symbol}/indicators")
def api_get_indicators(
    symbol: str,
    types: str = Query("ma", description="Comma-separated: ma,macd,kdj,boll"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    period: str = Query("daily", description="daily/weekly/monthly"),
    adjust: str = Query("raw", description="raw/qfq"),
):
    from config import QFQ_KLINE_DIR
    data_dir = QFQ_KLINE_DIR if adjust == "qfq" else RAW_KLINE_DIR
    filepath = data_dir / f"{symbol}.parquet"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    df = get_kline(filepath, start_date=start_date, end_date=end_date)
    if period in ("weekly", "monthly"):
        df = aggregate_kline(df, period=period)
    # ... rest stays the same
```

- [ ] **Step 2: Add test for adjust parameter**

Add to `backend/tests/test_api.py` in `TestStockRoutes`:

```python
    def test_get_kline_qfq(self):
        resp = client.get("/api/stocks/600028.SH/kline?adjust=qfq")
        assert resp.status_code in [200, 404]

    def test_get_indicators_qfq(self):
        resp = client.get("/api/stocks/600028.SH/indicators?types=ma&adjust=qfq")
        assert resp.status_code in [200, 404]
```

- [ ] **Step 3: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/stock.py backend/tests/test_api.py
git commit -m "feat: add adjust (raw/qfq) parameter to kline and indicators API"
```
