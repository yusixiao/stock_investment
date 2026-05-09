# 策略组（Strategy Group）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「策略组」实体，支持策略链路命名管理、一键/逐步执行、运行历史追踪，前端三层页面展示。

**Architecture:** 后端新增 `strategy_groups` 和 `group_runs` 两张 SQLite 表，新增 `GroupManager` 管理 CRUD 和执行调度。执行复用现有 `BacktestEngine`，每步创建 `backtest_tasks` 记录。前端拆分为策略组列表、运行历史、步骤详情三个独立页面，原 ScreenerPage 改造为策略调试页。

**Tech Stack:** Python, FastAPI, SQLite, Vue 3, axios

**Design Spec:** `docs/superpowers/specs/2026-05-09-strategy-group-design.md`

---

## File Structure

### 后端新建
- `backend/services/backtest/group_manager.py` — 策略组 CRUD + 运行调度（含逐步执行状态机）
- `backend/routers/strategy_group.py` — 策略组 API 路由
- `backend/tests/test_group_manager.py` — GroupManager 单元测试
- `backend/tests/test_strategy_group_api.py` — API 集成测试

### 后端修改
- `backend/main.py` — 注册新路由
- `backend/services/backtest/task_manager.py` — `_init_table` 中新增 `strategy_groups` 和 `group_runs` 建表

### 前端新建
- `frontend/src/views/StrategyGroupList.vue` — 第1层：策略组列表
- `frontend/src/views/StrategyGroupDetail.vue` — 第2层：运行历史
- `frontend/src/views/StrategyGroupEdit.vue` — 创建/编辑策略组
- `frontend/src/views/RunDetail.vue` — 第3层：步骤详情
- `frontend/src/views/StrategyDebug.vue` — 策略调试页（原 ScreenerPage 改造）

### 前端修改
- `frontend/src/router/index.js` — 新增路由
- `frontend/src/api/index.js` — 新增 API 函数
- `frontend/src/App.vue` — 更新导航栏

---

### Task 1: 数据库建表 + GroupManager 基础 CRUD

**Files:**
- Modify: `backend/services/backtest/task_manager.py`
- Create: `backend/services/backtest/group_manager.py`
- Create: `backend/tests/test_group_manager.py`

- [ ] **Step 1: 在 TaskManager._init_table 中新增建表语句**

在 `backend/services/backtest/task_manager.py` 的 `_init_table` 方法中，`conn.commit()` 前加入：

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS strategy_groups (
        group_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        pipeline TEXT NOT NULL,
        join_modes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS group_runs (
        run_id TEXT PRIMARY KEY,
        group_id TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        execution_mode TEXT NOT NULL,
        status TEXT NOT NULL,
        current_step INTEGER DEFAULT 0,
        steps_result TEXT,
        final_result TEXT,
        summary TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (group_id) REFERENCES strategy_groups(group_id)
    )
""")
```

- [ ] **Step 2: 写 GroupManager 的测试**

创建 `backend/tests/test_group_manager.py`：

```python
import json
import os
import tempfile
import pytest
from services.backtest.group_manager import GroupManager


@pytest.fixture
def gm(tmp_path):
    db_path = str(tmp_path / "test.db")
    return GroupManager(db_path=db_path)


class TestGroupCRUD:
    def test_create_group(self, gm):
        pipeline = [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {"fast": 5, "slow": 20}}]
        group_id = gm.create_group("测试策略组", pipeline, ["correlated"])
        assert group_id
        group = gm.get_group(group_id)
        assert group["name"] == "测试策略组"
        assert group["pipeline"] == pipeline
        assert group["join_modes"] == ["correlated"]

    def test_list_groups(self, gm):
        gm.create_group("组A", [{"filepath": "a.py", "class_name": "A"}], [])
        gm.create_group("组B", [{"filepath": "b.py", "class_name": "B"}], [])
        groups = gm.list_groups()
        assert len(groups) == 2

    def test_update_group(self, gm):
        gid = gm.create_group("旧名", [{"filepath": "a.py", "class_name": "A"}], [])
        gm.update_group(gid, name="新名")
        group = gm.get_group(gid)
        assert group["name"] == "新名"

    def test_delete_group(self, gm):
        gid = gm.create_group("待删", [{"filepath": "a.py", "class_name": "A"}], [])
        gm.delete_group(gid)
        assert gm.get_group(gid) is None
        assert len(gm.list_groups()) == 0

    def test_delete_group_cascades_runs(self, gm):
        gid = gm.create_group("有运行", [{"filepath": "a.py", "class_name": "A"}], [])
        run_id = gm.create_run(gid, "2024-01-01", "2024-12-31", "auto")
        gm.delete_group(gid)
        assert gm.get_run(run_id) is None
```

- [ ] **Step 3: 实现 GroupManager CRUD**

创建 `backend/services/backtest/group_manager.py`：

```python
import json
import sqlite3
import uuid
from datetime import datetime

from config import PORTFOLIO_DB


class GroupManager:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(PORTFOLIO_DB)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_group(self, name: str, pipeline: list[dict], join_modes: list[str] | None = None) -> str:
        group_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO strategy_groups (group_id, name, pipeline, join_modes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, name, json.dumps(pipeline, ensure_ascii=False), json.dumps(join_modes or [], ensure_ascii=False), now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return group_id

    def get_group(self, group_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM strategy_groups WHERE group_id = ?", (group_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "group_id": row["group_id"],
            "name": row["name"],
            "pipeline": json.loads(row["pipeline"]),
            "join_modes": json.loads(row["join_modes"]) if row["join_modes"] else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_groups(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM strategy_groups ORDER BY updated_at DESC").fetchall()
            result = []
            for row in rows:
                group = {
                    "group_id": row["group_id"],
                    "name": row["name"],
                    "pipeline": json.loads(row["pipeline"]),
                    "join_modes": json.loads(row["join_modes"]) if row["join_modes"] else [],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                run_row = conn.execute(
                    "SELECT count(*) as cnt, max(created_at) as last_run FROM group_runs WHERE group_id = ?",
                    (row["group_id"],),
                ).fetchone()
                group["run_count"] = run_row["cnt"]
                group["last_run"] = run_row["last_run"]
                result.append(group)
        finally:
            conn.close()
        return result

    def update_group(self, group_id: str, name: str | None = None, pipeline: list[dict] | None = None, join_modes: list[str] | None = None):
        conn = self._get_conn()
        try:
            updates = []
            params = []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if pipeline is not None:
                updates.append("pipeline = ?")
                params.append(json.dumps(pipeline, ensure_ascii=False))
            if join_modes is not None:
                updates.append("join_modes = ?")
                params.append(json.dumps(join_modes, ensure_ascii=False))
            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(group_id)
                conn.execute(f"UPDATE strategy_groups SET {', '.join(updates)} WHERE group_id = ?", params)
                conn.commit()
        finally:
            conn.close()

    def delete_group(self, group_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM group_runs WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM strategy_groups WHERE group_id = ?", (group_id,))
            conn.commit()
        finally:
            conn.close()

    def create_run(self, group_id: str, start_date: str | None, end_date: str | None, execution_mode: str) -> str:
        run_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO group_runs (run_id, group_id, start_date, end_date, execution_mode, status, current_step, steps_result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, group_id, start_date, end_date, execution_mode, "running", 0, "[]", now),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM group_runs WHERE run_id = ?", (run_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "group_id": row["group_id"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "execution_mode": row["execution_mode"],
            "status": row["status"],
            "current_step": row["current_step"],
            "steps_result": json.loads(row["steps_result"]) if row["steps_result"] else [],
            "final_result": json.loads(row["final_result"]) if row["final_result"] else None,
            "summary": json.loads(row["summary"]) if row["summary"] else None,
            "error": row["error"],
            "created_at": row["created_at"],
        }

    def list_runs(self, group_id: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM group_runs WHERE group_id = ? ORDER BY created_at DESC", (group_id,)).fetchall()
        finally:
            conn.close()
        result = []
        for row in rows:
            result.append({
                "run_id": row["run_id"],
                "group_id": row["group_id"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "execution_mode": row["execution_mode"],
                "status": row["status"],
                "current_step": row["current_step"],
                "summary": json.loads(row["summary"]) if row["summary"] else None,
                "error": row["error"],
                "created_at": row["created_at"],
            })
        return result

    def update_run_step(self, run_id: str, step: int, steps_result: list[dict]):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE group_runs SET current_step = ?, steps_result = ? WHERE run_id = ?",
                (step, json.dumps(steps_result, ensure_ascii=False), run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_run_status(self, run_id: str, status: str, final_result: dict | None = None, summary: dict | None = None, error: str | None = None):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE group_runs SET status = ?, final_result = ?, summary = ?, error = ? WHERE run_id = ?",
                (status, json.dumps(final_result, ensure_ascii=False) if final_result else None, json.dumps(summary, ensure_ascii=False) if summary else None, error, run_id),
            )
            conn.commit()
        finally:
            conn.close()
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest backend/tests/test_group_manager.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/group_manager.py backend/services/backtest/task_manager.py backend/tests/test_group_manager.py
git commit -m "feat: add strategy_groups and group_runs tables with GroupManager CRUD"
```

---

### Task 2: 策略组执行引擎（一键 + 逐步）

**Files:**
- Modify: `backend/services/backtest/group_manager.py`
- Modify: `backend/tests/test_group_manager.py`

- [ ] **Step 1: 写执行逻辑的测试**

在 `backend/tests/test_group_manager.py` 追加：

```python
from unittest.mock import patch, MagicMock
import pandas as pd
from services.backtest.group_manager import GroupManager, GroupRunner


@pytest.fixture
def runner(tmp_path):
    db_path = str(tmp_path / "test.db")
    from services.backtest.task_manager import TaskManager
    tm = TaskManager(db_path=db_path)
    gm = GroupManager(db_path=db_path)
    return GroupRunner(gm, tm)


class TestGroupRunner:
    def test_auto_run_single_screener(self, runner):
        gm = runner._group_manager
        pipeline = [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}}]
        gid = gm.create_group("单步选股", pipeline, [])

        mock_result = {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}]}
        with patch("services.backtest.group_manager._execute_step") as mock_exec:
            mock_exec.return_value = ("task123", mock_result)
            runner.run_auto(gid, "2024-01-01", "2024-12-31")

        run = gm.list_runs(gid)[0]
        assert run["status"] == "success"
        assert len(json.loads(run["steps_result"]) if isinstance(run.get("steps_result"), str) else run["steps_result"]) == 1

    def test_auto_run_chained_screeners(self, runner):
        gm = runner._group_manager
        pipeline = [
            {"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}},
            {"filepath": "strategies/examples/macd_screener.py", "class_name": "MacdScreener", "frequency": "daily", "params": {}},
        ]
        gid = gm.create_group("两步选股", pipeline, ["correlated"])

        results = [
            ("t1", {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}, {"symbol": "000002", "match_dates": ["2024-01-15"]}]}),
            ("t2", {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}]}),
        ]
        call_count = [0]

        def side_effect(*args, **kwargs):
            r = results[call_count[0]]
            call_count[0] += 1
            return r

        with patch("services.backtest.group_manager._execute_step", side_effect=side_effect):
            runner.run_auto(gid, "2024-01-01", "2024-12-31")

        run = gm.list_runs(gid)[0]
        assert run["status"] == "success"
        steps = run["steps_result"]
        assert len(steps) == 2
        assert steps[0]["output_count"] == 2
        assert steps[1]["input_count"] == 2

    def test_stepwise_run(self, runner):
        gm = runner._group_manager
        pipeline = [
            {"filepath": "a.py", "class_name": "A", "frequency": "daily", "params": {}},
            {"filepath": "b.py", "class_name": "B", "frequency": "daily", "params": {}},
        ]
        gid = gm.create_group("逐步", pipeline, ["correlated"])

        mock_result = {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}]}
        with patch("services.backtest.group_manager._execute_step") as mock_exec:
            mock_exec.return_value = ("t1", mock_result)
            run_id = runner.run_stepwise_start(gid, "2024-01-01", "2024-12-31")

        run = gm.get_run(run_id)
        assert run["status"] == "step_1_done"
        assert run["current_step"] == 1

        with patch("services.backtest.group_manager._execute_step") as mock_exec:
            mock_exec.return_value = ("t2", mock_result)
            runner.run_stepwise_next(run_id)

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        assert run["current_step"] == 2
```

- [ ] **Step 2: 实现 GroupRunner**

在 `backend/services/backtest/group_manager.py` 末尾追加：

```python
import threading
from pathlib import Path
from services.backtest.task_manager import TaskManager, task_manager as default_task_manager
from services.backtest.strategy_loader import load_strategy_from_file
from services.backtest.base import ScreenerStrategy, TraderStrategy


def _extract_symbols_from_result(result: dict) -> list[str]:
    screened = result.get("screened_symbols", [])
    if not screened:
        return []
    if isinstance(screened[0], str):
        return list(screened)
    return [item["symbol"] for item in screened]


def _execute_step(step_config: dict, start_date: str, end_date: str, symbols: list[str] | None, task_manager: TaskManager) -> tuple[str, dict]:
    from services.backtest.engine import BacktestEngine
    from services.qfq_cache import get_qfq_kline
    from config import RAW_KLINE_DIR, VALUATION_DIR, DIVIDEND_DIR, FINANCIAL_DIR
    import pandas as pd

    filepath = Path(step_config["filepath"])
    class_name = step_config["class_name"]
    params = step_config.get("params", {})

    classes = load_strategy_from_file(filepath)
    cls = next((c for c in classes if c.__name__ == class_name), None)
    if cls is None:
        raise ValueError(f"Strategy class {class_name} not found in {filepath}")
    instance = cls(param_overrides=params)

    screeners = []
    trader = None
    if isinstance(instance, TraderStrategy):
        trader = instance
    else:
        screeners = [instance]

    task_type = "backtest" if trader else "screener"
    task_id = task_manager.create_task(task_type=task_type, start_date=start_date, end_date=end_date)

    if symbols is not None:
        target_symbols = symbols
    else:
        target_symbols = [f.stem for f in RAW_KLINE_DIR.glob("*.parquet")]

    stock_data = {}
    for sym in target_symbols:
        df = get_qfq_kline(sym, start_date=start_date, end_date=end_date)
        if not df.empty:
            stock_data[sym] = df

    valuation_data = {}
    for sym in stock_data:
        fp = VALUATION_DIR / f"{sym}.parquet"
        if fp.exists():
            valuation_data[sym] = pd.read_parquet(fp).sort_values("date").reset_index(drop=True)

    dividend_data = {}
    for sym in stock_data:
        fp = DIVIDEND_DIR / f"{sym}.parquet"
        if fp.exists():
            dividend_data[sym] = pd.read_parquet(fp)

    financial_data = {}
    for sym in stock_data:
        fp = FINANCIAL_DIR / f"{sym}.parquet"
        if fp.exists():
            financial_data[sym] = pd.read_parquet(fp).sort_values("报告期").reset_index(drop=True)

    engine = BacktestEngine(
        stock_data=stock_data,
        screeners=screeners,
        trader=trader,
        valuation_data=valuation_data,
        dividend_data=dividend_data,
        financial_data=financial_data,
    )
    result = engine.run()
    task_manager.complete_task(task_id, result)
    return task_id, result


class GroupRunner:
    def __init__(self, group_manager: GroupManager | None = None, task_manager: TaskManager | None = None):
        self._group_manager = group_manager or group_manager_instance
        self._task_manager = task_manager or default_task_manager

    def run_auto(self, group_id: str, start_date: str, end_date: str):
        gm = self._group_manager
        group = gm.get_group(group_id)
        if group is None:
            raise ValueError(f"Group {group_id} not found")

        pipeline = group["pipeline"]
        join_modes = group["join_modes"]
        run_id = gm.create_run(group_id, start_date, end_date, "auto")

        def _do_run():
            try:
                steps_result = []
                prev_symbols = None
                for i, step_config in enumerate(pipeline):
                    join_mode = join_modes[i - 1] if i > 0 and i - 1 < len(join_modes) else "independent"
                    if i == 0 or join_mode == "independent":
                        input_symbols = None
                    else:
                        input_symbols = prev_symbols

                    input_count = len(input_symbols) if input_symbols else 0
                    task_id, result = _execute_step(step_config, start_date, end_date, input_symbols, self._task_manager)
                    output_symbols = _extract_symbols_from_result(result)

                    step_info = {
                        "step": i + 1,
                        "input_count": input_count,
                        "output_count": len(output_symbols),
                        "symbols": output_symbols,
                        "task_id": task_id,
                    }
                    steps_result.append(step_info)
                    gm.update_run_step(run_id, i + 1, steps_result)
                    prev_symbols = output_symbols

                final_result = result
                summary = self._build_summary(final_result)
                gm.update_run_status(run_id, "success", final_result=final_result, summary=summary)
            except Exception as e:
                gm.update_run_status(run_id, "failed", error=str(e))

        t = threading.Thread(target=_do_run, daemon=True)
        t.start()
        return run_id

    def run_stepwise_start(self, group_id: str, start_date: str, end_date: str) -> str:
        gm = self._group_manager
        group = gm.get_group(group_id)
        if group is None:
            raise ValueError(f"Group {group_id} not found")

        pipeline = group["pipeline"]
        run_id = gm.create_run(group_id, start_date, end_date, "stepwise")

        step_config = pipeline[0]
        task_id, result = _execute_step(step_config, start_date, end_date, None, self._task_manager)
        output_symbols = _extract_symbols_from_result(result)

        steps_result = [{
            "step": 1,
            "input_count": 0,
            "output_count": len(output_symbols),
            "symbols": output_symbols,
            "task_id": task_id,
        }]
        gm.update_run_step(run_id, 1, steps_result)

        if len(pipeline) == 1:
            summary = self._build_summary(result)
            gm.update_run_status(run_id, "success", final_result=result, summary=summary)
        else:
            gm.update_run_status(run_id, "step_1_done")

        return run_id

    def run_stepwise_next(self, run_id: str):
        gm = self._group_manager
        run = gm.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        group = gm.get_group(run["group_id"])
        pipeline = group["pipeline"]
        join_modes = group["join_modes"]
        current_step = run["current_step"]
        next_step_idx = current_step

        if next_step_idx >= len(pipeline):
            return

        steps_result = run["steps_result"]
        prev_symbols = steps_result[-1]["symbols"] if steps_result else None

        join_mode = join_modes[next_step_idx - 1] if next_step_idx > 0 and next_step_idx - 1 < len(join_modes) else "independent"
        if join_mode == "independent":
            input_symbols = None
        else:
            input_symbols = prev_symbols

        input_count = len(input_symbols) if input_symbols else 0
        step_config = pipeline[next_step_idx]
        task_id, result = _execute_step(step_config, run["start_date"], run["end_date"], input_symbols, self._task_manager)
        output_symbols = _extract_symbols_from_result(result)

        step_info = {
            "step": next_step_idx + 1,
            "input_count": input_count,
            "output_count": len(output_symbols),
            "symbols": output_symbols,
            "task_id": task_id,
        }
        steps_result.append(step_info)
        gm.update_run_step(run_id, next_step_idx + 1, steps_result)

        if next_step_idx + 1 >= len(pipeline):
            summary = self._build_summary(result)
            gm.update_run_status(run_id, "success", final_result=result, summary=summary)
        else:
            gm.update_run_status(run_id, f"step_{next_step_idx + 1}_done")

    def _build_summary(self, result: dict) -> dict | None:
        if "screened_symbols" in result:
            items = result["screened_symbols"]
            return {"screened_count": len(items)}
        if "metrics" in result:
            m = result["metrics"]
            return {
                "total_return": m.get("total_return"),
                "max_drawdown": m.get("max_drawdown"),
            }
        return None


group_manager_instance = GroupManager()
group_runner = GroupRunner()
```

- [ ] **Step 3: 运行测试**

Run: `python -m pytest backend/tests/test_group_manager.py -v`
Expected: All 8 tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/backtest/group_manager.py backend/tests/test_group_manager.py
git commit -m "feat: add GroupRunner with auto and stepwise execution"
```

---

### Task 3: 策略组 API 路由

**Files:**
- Create: `backend/routers/strategy_group.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_strategy_group_api.py`

- [ ] **Step 1: 写 API 测试**

创建 `backend/tests/test_strategy_group_api.py`：

```python
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestStrategyGroupAPI:
    def test_create_group(self, client):
        body = {
            "name": "测试组",
            "pipeline": [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}}],
            "join_modes": [],
        }
        resp = client.post("/api/backtest/groups", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "group_id" in data
        assert data["name"] == "测试组"

    def test_list_groups(self, client):
        body = {
            "name": "列表测试",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        client.post("/api/backtest/groups", json=body)
        resp = client.get("/api/backtest/groups")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_group(self, client):
        body = {
            "name": "详情测试",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]
        resp = client.get(f"/api/backtest/groups/{gid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "详情测试"

    def test_update_group(self, client):
        body = {
            "name": "旧名",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]
        resp = client.patch(f"/api/backtest/groups/{gid}", json={"name": "新名"})
        assert resp.status_code == 200
        get_resp = client.get(f"/api/backtest/groups/{gid}")
        assert get_resp.json()["name"] == "新名"

    def test_delete_group(self, client):
        body = {
            "name": "待删除",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]
        resp = client.delete(f"/api/backtest/groups/{gid}")
        assert resp.status_code == 200
        get_resp = client.get(f"/api/backtest/groups/{gid}")
        assert get_resp.status_code == 404

    def test_run_group(self, client):
        body = {
            "name": "运行测试",
            "pipeline": [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]

        with patch("routers.strategy_group.group_runner.run_auto") as mock_run:
            mock_run.return_value = "run123"
            resp = client.post(f"/api/backtest/groups/{gid}/run", json={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "execution_mode": "auto",
            })
        assert resp.status_code == 200
        assert resp.json()["run_id"] == "run123"

    def test_get_run_status(self, client):
        body = {
            "name": "状态测试",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]

        with patch("routers.strategy_group.group_runner.run_stepwise_start") as mock_start:
            mock_start.return_value = "run456"
            client.post(f"/api/backtest/groups/{gid}/run", json={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "execution_mode": "stepwise",
            })

        with patch("routers.strategy_group.group_manager_instance.get_run") as mock_get:
            mock_get.return_value = {
                "run_id": "run456",
                "group_id": gid,
                "status": "step_1_done",
                "current_step": 1,
                "steps_result": [],
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "execution_mode": "stepwise",
                "final_result": None,
                "summary": None,
                "error": None,
                "created_at": "2024-01-01T00:00:00",
            }
            resp = client.get("/api/backtest/runs/run456/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "step_1_done"
```

- [ ] **Step 2: 实现 API 路由**

创建 `backend/routers/strategy_group.py`：

```python
from fastapi import APIRouter, HTTPException, Body

from services.backtest.group_manager import group_manager_instance, group_runner

router = APIRouter(prefix="/api/backtest", tags=["strategy-group"])


@router.get("/groups")
def api_list_groups():
    return group_manager_instance.list_groups()


@router.post("/groups")
def api_create_group(body: dict = Body(...)):
    name = body.get("name")
    pipeline = body.get("pipeline", [])
    join_modes = body.get("join_modes", [])
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not pipeline:
        raise HTTPException(status_code=400, detail="pipeline cannot be empty")
    group_id = group_manager_instance.create_group(name, pipeline, join_modes)
    group = group_manager_instance.get_group(group_id)
    return group


@router.get("/groups/{group_id}")
def api_get_group(group_id: str):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.patch("/groups/{group_id}")
def api_update_group(group_id: str, body: dict = Body(...)):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group_manager_instance.update_group(
        group_id,
        name=body.get("name"),
        pipeline=body.get("pipeline"),
        join_modes=body.get("join_modes"),
    )
    return {"ok": True}


@router.delete("/groups/{group_id}")
def api_delete_group(group_id: str):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    group_manager_instance.delete_group(group_id)
    return {"ok": True}


@router.post("/groups/{group_id}/run")
def api_run_group(group_id: str, body: dict = Body(...)):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    execution_mode = body.get("execution_mode", "auto")

    if execution_mode == "stepwise":
        run_id = group_runner.run_stepwise_start(group_id, start_date, end_date)
    else:
        run_id = group_runner.run_auto(group_id, start_date, end_date)

    return {"run_id": run_id, "status": "running"}


@router.get("/groups/{group_id}/runs")
def api_list_runs(group_id: str):
    group = group_manager_instance.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group_manager_instance.list_runs(group_id)


@router.get("/runs/{run_id}")
def api_get_run(run_id: str):
    run = group_manager_instance.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/status")
def api_get_run_status(run_id: str):
    run = group_manager_instance.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "status": run["status"], "current_step": run["current_step"]}


@router.post("/runs/{run_id}/next-step")
def api_next_step(run_id: str):
    run = group_manager_instance.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run["status"].startswith("step_") or not run["status"].endswith("_done"):
        raise HTTPException(status_code=400, detail="Run is not waiting for next step")
    group_runner.run_stepwise_next(run_id)
    updated = group_manager_instance.get_run(run_id)
    return {"run_id": run_id, "status": updated["status"], "current_step": updated["current_step"]}
```

- [ ] **Step 3: 注册路由到 main.py**

在 `backend/main.py` 中，找到现有路由注册位置（如 `app.include_router(backtest.router)`），在其后追加：

```python
from routers import strategy_group
app.include_router(strategy_group.router)
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest backend/tests/test_strategy_group_api.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/strategy_group.py backend/main.py backend/tests/test_strategy_group_api.py
git commit -m "feat: add strategy group API routes"
```

---

### Task 4: 历史任务迁移 API

**Files:**
- Modify: `backend/services/backtest/group_manager.py`
- Modify: `backend/routers/strategy_group.py`
- Modify: `backend/tests/test_group_manager.py`

- [ ] **Step 1: 写迁移逻辑的测试**

在 `backend/tests/test_group_manager.py` 追加：

```python
class TestMigration:
    def test_migrate_chain(self, gm, tmp_path):
        db_path = str(tmp_path / "test.db")
        from services.backtest.task_manager import TaskManager
        tm = TaskManager(db_path=db_path)

        t1 = tm.create_task(task_type="screener", pipeline_info={"strategies": [{"class_name": "MaCross", "name": "均线交叉"}]}, start_date="2024-01-01", end_date="2024-12-31")
        tm.complete_task(t1, {"screened_symbols": ["000001", "000002"]})
        t2 = tm.create_task(task_type="screener", pipeline_info={"strategies": [{"class_name": "MacdFilter", "name": "MACD过滤"}]}, start_date="2024-01-01", end_date="2024-12-31", source_task_id=t1)
        tm.complete_task(t2, {"screened_symbols": ["000001"]})

        gm_real = GroupManager(db_path=db_path)
        count = gm_real.migrate_from_tasks(tm)
        assert count == 1
        groups = gm_real.list_groups()
        assert len(groups) == 1
        assert len(groups[0]["pipeline"]) == 2

    def test_migrate_no_chains(self, gm, tmp_path):
        db_path = str(tmp_path / "test.db")
        from services.backtest.task_manager import TaskManager
        tm = TaskManager(db_path=db_path)

        t1 = tm.create_task(task_type="screener", pipeline_info={"strategies": [{"class_name": "A"}]}, start_date="2024-01-01", end_date="2024-12-31")
        tm.complete_task(t1, {"screened_symbols": ["000001"]})

        gm_real = GroupManager(db_path=db_path)
        count = gm_real.migrate_from_tasks(tm)
        assert count == 0
```

- [ ] **Step 2: 实现 migrate_from_tasks**

在 `GroupManager` 类中追加方法：

```python
def migrate_from_tasks(self, task_manager: "TaskManager") -> int:
    tasks = task_manager.list_tasks(show_deleted=False)
    source_map = {}
    task_map = {}
    for t in tasks:
        task_map[t["task_id"]] = t
        if t.get("source_task_id"):
            source_map[t["task_id"]] = t["source_task_id"]

    children = {}
    for child_id, parent_id in source_map.items():
        children.setdefault(parent_id, []).append(child_id)

    roots = set()
    for child_id in source_map:
        parent_id = source_map[child_id]
        if parent_id not in source_map:
            roots.add(parent_id)

    count = 0
    for root_id in roots:
        chain = [root_id]
        current = root_id
        while current in children:
            next_ids = children[current]
            current = next_ids[0]
            chain.append(current)

        pipeline = []
        for tid in chain:
            result = task_manager.get_result(tid)
            if result and result.get("pipeline_info"):
                pi = result["pipeline_info"]
                strategies = pi.get("strategies", [pi] if "class_name" in pi else [])
                for s in strategies:
                    pipeline.append({
                        "filepath": s.get("filepath", ""),
                        "class_name": s.get("class_name", ""),
                        "frequency": s.get("frequency", "daily"),
                        "params": s.get("params", {}),
                    })

        if len(pipeline) < 2:
            continue

        from datetime import datetime
        name = f"迁移-{datetime.now().strftime('%Y%m%d')}-#{count + 1}"
        first_task = task_manager.get_result(chain[0])
        start_date = first_task.get("start_date", "")
        end_date = first_task.get("end_date", "")

        join_modes = ["correlated"] * (len(pipeline) - 1)
        group_id = self.create_group(name, pipeline, join_modes)

        run_id = self.create_run(group_id, start_date, end_date, "auto")
        steps_result = []
        last_result = None
        for i, tid in enumerate(chain):
            r = task_manager.get_result(tid)
            result_data = r.get("result") or {}
            syms = _extract_symbols_from_result(result_data) if result_data else []
            steps_result.append({
                "step": i + 1,
                "input_count": 0 if i == 0 else steps_result[i - 1]["output_count"],
                "output_count": len(syms),
                "symbols": syms,
                "task_id": tid,
            })
            last_result = result_data

        self.update_run_step(run_id, len(chain), steps_result)
        summary = None
        if last_result:
            if "screened_symbols" in last_result:
                summary = {"screened_count": len(last_result["screened_symbols"])}
            elif "metrics" in last_result:
                m = last_result["metrics"]
                summary = {"total_return": m.get("total_return"), "max_drawdown": m.get("max_drawdown")}
        self.update_run_status(run_id, "success", final_result=last_result, summary=summary)
        count += 1

    return count
```

- [ ] **Step 3: 在路由中添加迁移接口**

在 `backend/routers/strategy_group.py` 追加：

```python
from services.backtest.task_manager import task_manager

@router.post("/groups/migrate")
def api_migrate_groups():
    count = group_manager_instance.migrate_from_tasks(task_manager)
    return {"migrated": count}
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest backend/tests/test_group_manager.py::TestMigration -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/group_manager.py backend/routers/strategy_group.py backend/tests/test_group_manager.py
git commit -m "feat: add historical task migration to strategy groups"
```

---

### Task 5: 前端 API 层 + 路由更新

**Files:**
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 添加前端 API 函数**

在 `frontend/src/api/index.js` 中 `export default api` 之前追加：

```javascript
export function fetchGroups() {
  return api.get('/backtest/groups')
}

export function createGroup(body) {
  return api.post('/backtest/groups', body)
}

export function fetchGroup(groupId) {
  return api.get(`/backtest/groups/${groupId}`)
}

export function updateGroup(groupId, body) {
  return api.patch(`/backtest/groups/${groupId}`, body)
}

export function deleteGroup(groupId) {
  return api.delete(`/backtest/groups/${groupId}`)
}

export function runGroup(groupId, body) {
  return api.post(`/backtest/groups/${groupId}/run`, body)
}

export function fetchGroupRuns(groupId) {
  return api.get(`/backtest/groups/${groupId}/runs`)
}

export function fetchRun(runId) {
  return api.get(`/backtest/runs/${runId}`)
}

export function fetchRunStatus(runId) {
  return api.get(`/backtest/runs/${runId}/status`)
}

export function nextStep(runId) {
  return api.post(`/backtest/runs/${runId}/next-step`)
}

export function migrateGroups() {
  return api.post('/backtest/groups/migrate')
}
```

- [ ] **Step 2: 更新路由**

替换 `frontend/src/router/index.js` 内容：

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'StockList', component: () => import('../views/StockList.vue') },
  { path: '/stock/:symbol', name: 'StockDetail', component: () => import('../views/StockDetail.vue') },
  { path: '/strategies', name: 'StrategyList', component: () => import('../views/StrategyList.vue') },
  { path: '/debug', name: 'StrategyDebug', component: () => import('../views/StrategyDebug.vue') },
  { path: '/backtest', name: 'StrategyGroupList', component: () => import('../views/StrategyGroupList.vue') },
  { path: '/backtest/group/create', name: 'StrategyGroupCreate', component: () => import('../views/StrategyGroupEdit.vue') },
  { path: '/backtest/group/:groupId/edit', name: 'StrategyGroupEditExisting', component: () => import('../views/StrategyGroupEdit.vue') },
  { path: '/backtest/group/:groupId', name: 'StrategyGroupDetail', component: () => import('../views/StrategyGroupDetail.vue') },
  { path: '/backtest/group/:groupId/run/:runId', name: 'RunDetail', component: () => import('../views/RunDetail.vue') },
  { path: '/backtest/result/:id', name: 'BacktestResult', component: () => import('../views/BacktestResult.vue') },
  { path: '/portfolio', name: 'PortfolioList', component: () => import('../views/PortfolioList.vue') },
  { path: '/portfolio/:id', name: 'PortfolioDetail', component: () => import('../views/PortfolioDetail.vue') },
  { path: '/compare', name: 'ComparePage', component: () => import('../views/ComparePage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
```

- [ ] **Step 3: 更新 App.vue 导航栏**

找到 `App.vue` 中的导航链接，将 `选股` 改为 `策略调试` 并指向 `/debug`，将 `回测` 指向 `/backtest`：

导航项改为：
- A股列表 → `/`
- 策略调试 → `/debug`
- 回测 → `/backtest`
- 组合管理 → `/portfolio`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/index.js frontend/src/router/index.js frontend/src/App.vue
git commit -m "feat: add frontend API functions and routes for strategy groups"
```

---

### Task 6: 策略调试页（StrategyDebug.vue）

**Files:**
- Create: `frontend/src/views/StrategyDebug.vue`

- [ ] **Step 1: 创建 StrategyDebug.vue**

基于现有 `ScreenerPage.vue` 复制并增强，添加历史调试任务列表：

```vue
<template>
  <div class="debug-page">
    <h1>策略调试</h1>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" mode="screener" />
    <ParamEditor :pipeline="pipeline" @update:overrides="overrides = $event" />
    <div class="date-range">
      <label>开始日期: <input v-model="startDate" type="date" min="2010-01-04" /></label>
      <label>结束日期: <input v-model="endDate" type="date" min="2010-01-04" /></label>
    </div>
    <button class="run-btn" @click="runDebug" :disabled="!pipeline.length || running">
      {{ running ? '运行中...' : '运行调试' }}
    </button>
    <div v-if="taskId" class="status">
      <p>任务ID: {{ taskId }} | 状态: {{ status }}</p>
      <div v-if="progress && status === 'running'" class="progress-info">
        <p class="progress-phase">{{ progress.phase }}</p>
        <div v-if="progress.total > 0" class="progress-bar-wrap">
          <div class="progress-bar" :style="{ width: progressPct + '%' }"></div>
        </div>
        <p v-if="progress.total > 0" class="progress-text">{{ progress.current }} / {{ progress.total }} ({{ progressPct }}%)</p>
      </div>
      <div v-if="status === 'success' && result" class="result">
        <h2>选股结果 ({{ result.screened_symbols ? result.screened_symbols.length : 0 }} 只)</h2>
        <div class="symbol-grid">
          <span v-for="sym in (result.screened_symbols || [])" :key="typeof sym === 'string' ? sym : sym.symbol" class="symbol-tag" @click="$router.push('/stock/' + (typeof sym === 'string' ? sym : sym.symbol))">
            {{ typeof sym === 'string' ? sym : sym.symbol }}
          </span>
        </div>
      </div>
      <p v-if="status === 'failed'" class="error">运行失败</p>
    </div>
    <div class="task-history">
      <h3>调试历史</h3>
      <table v-if="tasks.length" class="task-table">
        <thead>
          <tr><th>任务ID</th><th>状态</th><th>摘要</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id">
            <td>{{ t.task_id }}</td>
            <td><span :class="'task-status ' + t.status">{{ statusText(t.status) }}</span></td>
            <td>{{ formatSummary(t) }}</td>
            <td>{{ t.created_at }}</td>
            <td>
              <button v-if="t.status === 'success'" class="view-btn" @click="$router.push('/backtest/result/' + t.task_id)">查看</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无调试记录</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchStrategies, runBacktest, fetchBacktestStatus, fetchBacktestResult, fetchBacktestTasks } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'
import ParamEditor from '../components/ParamEditor.vue'

const strategies = ref([])
const pipeline = ref([])
const overrides = ref({})
const startDate = ref('')
const endDate = ref('')
const taskId = ref('')
const status = ref('')
const running = ref(false)
const result = ref(null)
const progress = ref(null)
const tasks = ref([])
const progressPct = computed(() => {
  if (!progress.value || !progress.value.total) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})
let pollTimer = null

const statusMap = { running: '运行中', success: '成功', failed: '失败' }
function statusText(s) { return statusMap[s] || s }

function formatSummary(t) {
  if (!t.summary) return '-'
  if (t.summary.screened_count !== undefined) return `选出 ${t.summary.screened_count} 只`
  return '-'
}

async function loadTasks() {
  try {
    const { data } = await fetchBacktestTasks()
    tasks.value = data.filter(t => t.task_type === 'screener' || t.task_type === 'debug')
  } catch {}
}

async function runDebug() {
  running.value = true
  progress.value = null
  result.value = null
  const body = {
    pipeline: pipeline.value.map(s => ({ filepath: s.filepath, class_name: s.class_name })),
    param_overrides: overrides.value,
  }
  if (startDate.value) body.start_date = startDate.value
  if (endDate.value) body.end_date = endDate.value
  const { data } = await runBacktest(body)
  taskId.value = data.task_id
  status.value = 'running'
  pollTimer = setInterval(pollStatus, 2000)
}

async function pollStatus() {
  if (!taskId.value) return
  try {
    const { data } = await fetchBacktestStatus(taskId.value)
    status.value = data.status
    progress.value = data.progress || null
    if (data.status !== 'running') {
      running.value = false
      progress.value = null
      clearInterval(pollTimer)
      if (data.status === 'success') {
        const { data: r } = await fetchBacktestResult(taskId.value)
        result.value = r.result
      }
      loadTasks()
    }
  } catch {
    status.value = 'failed'
    running.value = false
    progress.value = null
    clearInterval(pollTimer)
  }
}

onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
  loadTasks()
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.debug-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.date-range { margin-top: 16px; display: flex; gap: 16px; align-items: center; }
.date-range label { font-size: 14px; }
.date-range input { padding: 4px 8px; margin-left: 4px; }
.run-btn { margin-top: 16px; padding: 10px 24px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.run-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
.status { margin-top: 16px; padding: 12px; background: #f5f7fa; border-radius: 4px; }
.result { margin-top: 12px; }
.symbol-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.symbol-tag { padding: 4px 10px; background: #ecf5ff; border: 1px solid #b3d8ff; border-radius: 4px; cursor: pointer; font-size: 13px; }
.symbol-tag:hover { background: #409eff; color: white; }
.view-btn { padding: 4px 12px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.error { color: #f56c6c; }
.progress-info { margin-top: 8px; }
.progress-phase { font-size: 13px; color: #606266; margin: 0 0 6px; }
.progress-bar-wrap { width: 100%; height: 16px; background: #e4e7ed; border-radius: 8px; overflow: hidden; }
.progress-bar { height: 100%; background: #409eff; border-radius: 8px; transition: width 0.3s ease; }
.progress-text { font-size: 12px; color: #909399; margin: 4px 0 0; }
.task-history { margin-top: 32px; }
.task-history h3 { font-size: 16px; color: #303133; margin-bottom: 12px; }
.task-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.task-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.task-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.task-status { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.task-status.success { background: #e8f5e9; color: #2e7d32; }
.task-status.failed { background: #ffebee; color: #c62828; }
.task-status.running { background: #fff3e0; color: #e65100; }
.empty { color: #c0c4cc; font-size: 13px; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/StrategyDebug.vue
git commit -m "feat: add strategy debug page (replaces screener page)"
```

---

### Task 7: 策略组列表页（StrategyGroupList.vue）

**Files:**
- Create: `frontend/src/views/StrategyGroupList.vue`

- [ ] **Step 1: 创建 StrategyGroupList.vue**

```vue
<template>
  <div class="group-list-page">
    <div class="page-header">
      <h1>回测</h1>
      <div class="header-actions">
        <button class="btn-primary" @click="$router.push('/backtest/group/create')">+ 创建策略组</button>
        <button class="btn-secondary" @click="doMigrate" :disabled="migrating">{{ migrating ? '迁移中...' : '迁移历史任务' }}</button>
      </div>
    </div>
    <div v-if="migrateMsg" class="migrate-msg">{{ migrateMsg }}</div>
    <div v-if="groups.length" class="group-cards">
      <div v-for="g in groups" :key="g.group_id" class="group-card" @click="$router.push('/backtest/group/' + g.group_id)">
        <div class="card-header">
          <h3>{{ g.name }}</h3>
          <button class="btn-run" @click.stop="openRunDialog(g)">运行</button>
        </div>
        <div class="pipeline-flow">
          <span v-for="(step, i) in g.pipeline" :key="i" class="flow-step">
            <span :class="'freq-badge freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
            <span class="step-name">{{ step.class_name }}</span>
            <span v-if="i < g.pipeline.length - 1" class="flow-arrow">→</span>
          </span>
        </div>
        <div class="card-footer">
          <span>已运行 {{ g.run_count }} 次</span>
          <span v-if="g.last_run">| 最近: {{ g.last_run }}</span>
        </div>
      </div>
    </div>
    <p v-else class="empty">暂无策略组，点击「创建策略组」开始</p>
    <div v-if="showRunDialog" class="dialog-overlay" @click.self="showRunDialog = false">
      <div class="dialog">
        <h3>运行策略组: {{ runTarget.name }}</h3>
        <div class="dialog-form">
          <label>开始日期: <input v-model="runStartDate" type="date" min="2010-01-04" /></label>
          <label>结束日期: <input v-model="runEndDate" type="date" min="2010-01-04" /></label>
          <label>执行模式:
            <select v-model="runMode">
              <option value="auto">一键执行</option>
              <option value="stepwise">逐步执行</option>
            </select>
          </label>
        </div>
        <div class="dialog-actions">
          <button class="btn-primary" @click="doRun">开始运行</button>
          <button class="btn-secondary" @click="showRunDialog = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchGroups, runGroup, migrateGroups } from '../api'

const router = useRouter()
const groups = ref([])
const migrating = ref(false)
const migrateMsg = ref('')
const showRunDialog = ref(false)
const runTarget = ref(null)
const runStartDate = ref('')
const runEndDate = ref('')
const runMode = ref('auto')

const freqMap = { daily: '日线', weekly: '周线', monthly: '月线' }
function freqLabel(f) { return freqMap[f] || '日线' }

async function loadGroups() {
  const { data } = await fetchGroups()
  groups.value = data
}

async function doMigrate() {
  migrating.value = true
  migrateMsg.value = ''
  try {
    const { data } = await migrateGroups()
    migrateMsg.value = `迁移完成，共迁移 ${data.migrated} 个策略组`
    loadGroups()
  } catch (e) {
    migrateMsg.value = '迁移失败'
  } finally {
    migrating.value = false
  }
}

function openRunDialog(g) {
  runTarget.value = g
  runStartDate.value = ''
  runEndDate.value = ''
  runMode.value = 'auto'
  showRunDialog.value = true
}

async function doRun() {
  const { data } = await runGroup(runTarget.value.group_id, {
    start_date: runStartDate.value || undefined,
    end_date: runEndDate.value || undefined,
    execution_mode: runMode.value,
  })
  showRunDialog.value = false
  router.push(`/backtest/group/${runTarget.value.group_id}/run/${data.run_id}`)
}

onMounted(loadGroups)
</script>

<style scoped>
.group-list-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header-actions { display: flex; gap: 12px; }
.btn-primary { padding: 8px 16px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-secondary { padding: 8px 16px; background: white; color: #606266; border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-secondary:disabled { color: #c0c4cc; cursor: not-allowed; }
.migrate-msg { padding: 8px 12px; background: #f0f9eb; border: 1px solid #c2e7b0; border-radius: 4px; margin-bottom: 16px; font-size: 13px; color: #67c23a; }
.group-cards { display: flex; flex-direction: column; gap: 16px; }
.group-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 16px; cursor: pointer; transition: box-shadow 0.2s; }
.group-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-header h3 { margin: 0; font-size: 16px; color: #303133; }
.btn-run { padding: 4px 12px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.pipeline-flow { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.flow-step { display: flex; align-items: center; gap: 4px; }
.freq-badge { padding: 2px 6px; border-radius: 3px; font-size: 11px; color: white; }
.freq-daily { background: #909399; }
.freq-weekly { background: #e6a23c; }
.freq-monthly { background: #f56c6c; }
.step-name { font-size: 13px; color: #606266; }
.flow-arrow { color: #c0c4cc; margin: 0 4px; }
.card-footer { margin-top: 12px; font-size: 12px; color: #909399; }
.empty { color: #c0c4cc; font-size: 14px; text-align: center; margin-top: 40px; }
.dialog-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.dialog { background: white; border-radius: 8px; padding: 24px; min-width: 400px; }
.dialog h3 { margin: 0 0 16px; font-size: 16px; }
.dialog-form { display: flex; flex-direction: column; gap: 12px; }
.dialog-form label { font-size: 14px; display: flex; align-items: center; gap: 8px; }
.dialog-form input, .dialog-form select { padding: 4px 8px; }
.dialog-actions { margin-top: 20px; display: flex; gap: 12px; justify-content: flex-end; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/StrategyGroupList.vue
git commit -m "feat: add strategy group list page"
```

---

### Task 8: 策略组创建/编辑页（StrategyGroupEdit.vue）

**Files:**
- Create: `frontend/src/views/StrategyGroupEdit.vue`

- [ ] **Step 1: 创建 StrategyGroupEdit.vue**

```vue
<template>
  <div class="group-edit-page">
    <h1>{{ isEdit ? '编辑策略组' : '创建策略组' }}</h1>
    <div class="form-section">
      <label>策略组名称: <input v-model="name" type="text" placeholder="输入策略组名称" /></label>
    </div>
    <PipelineBuilder :strategies="strategies" v-model:pipeline="pipeline" v-model:joinModes="joinModes" mode="backtest" />
    <div class="actions">
      <button class="btn-primary" @click="save" :disabled="!name || !pipeline.length">{{ isEdit ? '保存修改' : '创建' }}</button>
      <button class="btn-secondary" @click="$router.back()">取消</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchStrategies, fetchGroup, createGroup, updateGroup } from '../api'
import PipelineBuilder from '../components/PipelineBuilder.vue'

const route = useRoute()
const router = useRouter()
const groupId = computed(() => route.params.groupId)
const isEdit = computed(() => !!groupId.value)

const strategies = ref([])
const name = ref('')
const pipeline = ref([])
const joinModes = ref([])

async function save() {
  const pipelineData = pipeline.value.map(s => ({
    filepath: s.filepath,
    class_name: s.class_name,
    frequency: s.frequency || 'daily',
    params: s.params || {},
  }))
  if (isEdit.value) {
    await updateGroup(groupId.value, { name: name.value, pipeline: pipelineData, join_modes: joinModes.value })
    router.push(`/backtest/group/${groupId.value}`)
  } else {
    const { data } = await createGroup({ name: name.value, pipeline: pipelineData, join_modes: joinModes.value })
    router.push(`/backtest/group/${data.group_id}`)
  }
}

onMounted(async () => {
  const { data } = await fetchStrategies()
  strategies.value = data
  if (isEdit.value) {
    const { data: group } = await fetchGroup(groupId.value)
    name.value = group.name
    pipeline.value = group.pipeline
    joinModes.value = group.join_modes || []
  }
})
</script>

<style scoped>
.group-edit-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.form-section { margin-bottom: 16px; }
.form-section label { font-size: 14px; display: flex; align-items: center; gap: 8px; }
.form-section input { padding: 6px 12px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 14px; width: 300px; }
.actions { margin-top: 20px; display: flex; gap: 12px; }
.btn-primary { padding: 8px 16px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-primary:disabled { background: #c0c4cc; cursor: not-allowed; }
.btn-secondary { padding: 8px 16px; background: white; color: #606266; border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 14px; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/StrategyGroupEdit.vue
git commit -m "feat: add strategy group create/edit page"
```

---

### Task 9: 策略组详情页 — 运行历史（StrategyGroupDetail.vue）

**Files:**
- Create: `frontend/src/views/StrategyGroupDetail.vue`

- [ ] **Step 1: 创建 StrategyGroupDetail.vue**

```vue
<template>
  <div class="group-detail-page">
    <div class="page-header">
      <button class="btn-back" @click="$router.push('/backtest')">← 返回</button>
      <h1>{{ group?.name }}</h1>
      <div class="header-actions">
        <button class="btn-primary" @click="openRunDialog">运行</button>
        <button class="btn-secondary" @click="$router.push(`/backtest/group/${groupId}/edit`)">编辑</button>
        <button class="btn-danger" @click="doDelete">删除</button>
      </div>
    </div>
    <div v-if="group" class="pipeline-display">
      <span v-for="(step, i) in group.pipeline" :key="i" class="flow-step">
        <span :class="'freq-badge freq-' + (step.frequency || 'daily')">{{ freqLabel(step.frequency) }}</span>
        <span class="step-name">{{ step.class_name }}</span>
        <span v-if="i < group.pipeline.length - 1" class="flow-arrow">
          {{ joinModeLabel(group.join_modes, i) }}→
        </span>
      </span>
    </div>
    <h2>运行历史</h2>
    <table v-if="runs.length" class="run-table">
      <thead>
        <tr><th>#</th><th>运行时间</th><th>日期范围</th><th>模式</th><th>状态</th><th>结果摘要</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in runs" :key="r.run_id">
          <td>{{ runs.length - i }}</td>
          <td>{{ r.created_at }}</td>
          <td>{{ r.start_date || '-' }} ~ {{ r.end_date || '-' }}</td>
          <td>{{ r.execution_mode === 'auto' ? '一键' : '逐步' }}</td>
          <td><span :class="'status-badge status-' + statusClass(r.status)">{{ statusText(r.status) }}</span></td>
          <td>{{ formatSummary(r.summary) }}</td>
          <td><button class="view-btn" @click="$router.push(`/backtest/group/${groupId}/run/${r.run_id}`)">查看</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty">暂无运行记录</p>
    <div v-if="showRunDialog" class="dialog-overlay" @click.self="showRunDialog = false">
      <div class="dialog">
        <h3>运行策略组</h3>
        <div class="dialog-form">
          <label>开始日期: <input v-model="runStartDate" type="date" min="2010-01-04" /></label>
          <label>结束日期: <input v-model="runEndDate" type="date" min="2010-01-04" /></label>
          <label>执行模式:
            <select v-model="runMode">
              <option value="auto">一键执行</option>
              <option value="stepwise">逐步执行</option>
            </select>
          </label>
        </div>
        <div class="dialog-actions">
          <button class="btn-primary" @click="doRun">开始</button>
          <button class="btn-secondary" @click="showRunDialog = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchGroup, fetchGroupRuns, runGroup, deleteGroup } from '../api'

const route = useRoute()
const router = useRouter()
const groupId = route.params.groupId

const group = ref(null)
const runs = ref([])
const showRunDialog = ref(false)
const runStartDate = ref('')
const runEndDate = ref('')
const runMode = ref('auto')

const freqMap = { daily: '日线', weekly: '周线', monthly: '月线' }
function freqLabel(f) { return freqMap[f] || '日线' }

function joinModeLabel(modes, i) {
  if (!modes || i >= modes.length) return ''
  return modes[i] === 'correlated' ? '[关联]' : '[独立]'
}

function statusClass(s) {
  if (s === 'success') return 'success'
  if (s === 'failed') return 'failed'
  if (s === 'running') return 'running'
  return 'pending'
}

function statusText(s) {
  if (s === 'success') return '成功'
  if (s === 'failed') return '失败'
  if (s === 'running') return '运行中'
  if (s.startsWith('step_') && s.endsWith('_done')) return `第${s.match(/\d+/)[0]}步完成`
  return s
}

function formatSummary(s) {
  if (!s) return '-'
  if (s.screened_count !== undefined) return `选出 ${s.screened_count} 只`
  if (s.total_return !== undefined) return `收益 ${(s.total_return * 100).toFixed(2)}%`
  return '-'
}

function openRunDialog() {
  runStartDate.value = ''
  runEndDate.value = ''
  runMode.value = 'auto'
  showRunDialog.value = true
}

async function doRun() {
  const { data } = await runGroup(groupId, {
    start_date: runStartDate.value || undefined,
    end_date: runEndDate.value || undefined,
    execution_mode: runMode.value,
  })
  showRunDialog.value = false
  router.push(`/backtest/group/${groupId}/run/${data.run_id}`)
}

async function doDelete() {
  if (!confirm('确认删除此策略组及所有运行记录？')) return
  await deleteGroup(groupId)
  router.push('/backtest')
}

onMounted(async () => {
  const { data: g } = await fetchGroup(groupId)
  group.value = g
  const { data: r } = await fetchGroupRuns(groupId)
  runs.value = r
})
</script>

<style scoped>
.group-detail-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.page-header h1 { flex: 1; margin: 0; }
.btn-back { background: none; border: none; color: #409eff; cursor: pointer; font-size: 14px; }
.header-actions { display: flex; gap: 8px; }
.btn-primary { padding: 6px 14px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-secondary { padding: 6px 14px; background: white; color: #606266; border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-danger { padding: 6px 14px; background: #f56c6c; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.pipeline-display { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-bottom: 24px; padding: 12px; background: #f5f7fa; border-radius: 6px; }
.flow-step { display: flex; align-items: center; gap: 4px; }
.freq-badge { padding: 2px 6px; border-radius: 3px; font-size: 11px; color: white; }
.freq-daily { background: #909399; }
.freq-weekly { background: #e6a23c; }
.freq-monthly { background: #f56c6c; }
.step-name { font-size: 13px; color: #606266; }
.flow-arrow { color: #909399; margin: 0 4px; font-size: 12px; }
.run-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.run-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.run-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.status-success { background: #e8f5e9; color: #2e7d32; }
.status-failed { background: #ffebee; color: #c62828; }
.status-running { background: #fff3e0; color: #e65100; }
.status-pending { background: #e3f2fd; color: #1565c0; }
.view-btn { padding: 4px 12px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
.empty { color: #c0c4cc; font-size: 14px; }
.dialog-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.dialog { background: white; border-radius: 8px; padding: 24px; min-width: 400px; }
.dialog h3 { margin: 0 0 16px; font-size: 16px; }
.dialog-form { display: flex; flex-direction: column; gap: 12px; }
.dialog-form label { font-size: 14px; display: flex; align-items: center; gap: 8px; }
.dialog-form input, .dialog-form select { padding: 4px 8px; }
.dialog-actions { margin-top: 20px; display: flex; gap: 12px; justify-content: flex-end; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/StrategyGroupDetail.vue
git commit -m "feat: add strategy group detail page with run history"
```

---

### Task 10: 运行详情页（RunDetail.vue）

**Files:**
- Create: `frontend/src/views/RunDetail.vue`

- [ ] **Step 1: 创建 RunDetail.vue**

```vue
<template>
  <div class="run-detail-page">
    <div class="page-header">
      <button class="btn-back" @click="$router.push(`/backtest/group/${groupId}`)">← 返回</button>
      <h1>运行详情</h1>
      <span v-if="run" class="run-meta">{{ run.start_date || '-' }} ~ {{ run.end_date || '-' }} | {{ run.execution_mode === 'auto' ? '一键执行' : '逐步执行' }}</span>
    </div>
    <div v-if="run" class="run-content">
      <div class="steps-flow">
        <div v-for="(step, i) in run.steps_result" :key="i" class="step-card" :class="{ active: expandedStep === i }" @click="expandedStep = expandedStep === i ? -1 : i">
          <div class="step-header">
            <span class="step-num">步骤 {{ step.step }}</span>
            <span class="step-io">{{ step.input_count || '全量' }} → {{ step.output_count }}</span>
          </div>
          <div v-if="expandedStep === i && step.symbols" class="step-symbols">
            <span v-for="sym in step.symbols" :key="sym" class="symbol-tag" @click.stop="$router.push('/stock/' + sym)">{{ sym }}</span>
          </div>
        </div>
        <div v-if="isStepwise && !isComplete" class="next-step-section">
          <button class="btn-primary" @click="doNextStep" :disabled="stepping">
            {{ stepping ? '执行中...' : '执行下一步' }}
          </button>
        </div>
      </div>
      <div v-if="run.status === 'running'" class="running-msg">运行中...</div>
      <div v-if="run.error" class="error-msg">错误: {{ run.error }}</div>
      <div v-if="run.final_result && run.final_result.screened_symbols" class="final-result">
        <h2>最终结果 ({{ run.final_result.screened_symbols.length }} 只)</h2>
        <table class="result-table">
          <thead>
            <tr><th>代码</th><th>匹配次数</th><th>匹配日期</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in finalSymbols" :key="item.symbol">
              <td><a @click="$router.push('/stock/' + item.symbol)">{{ item.symbol }}</a></td>
              <td>{{ item.match_count }}</td>
              <td>{{ item.dates }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="run.final_result && run.final_result.metrics" class="final-result">
        <h2>回测结果</h2>
        <button class="view-btn" @click="$router.push('/backtest/result/' + lastTaskId)">查看详细回测结果</button>
      </div>
    </div>
    <div v-else class="loading">加载中...</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchRun, fetchRunStatus, nextStep } from '../api'

const route = useRoute()
const groupId = route.params.groupId
const runId = route.params.runId

const run = ref(null)
const expandedStep = ref(-1)
const stepping = ref(false)
let pollTimer = null

const isStepwise = computed(() => run.value?.execution_mode === 'stepwise')
const isComplete = computed(() => run.value?.status === 'success' || run.value?.status === 'failed')

const finalSymbols = computed(() => {
  if (!run.value?.final_result?.screened_symbols) return []
  const items = run.value.final_result.screened_symbols
  return items.map(item => {
    if (typeof item === 'string') return { symbol: item, match_count: 0, dates: '' }
    return {
      symbol: item.symbol,
      match_count: item.match_dates?.length || 0,
      dates: (item.match_dates || []).slice(0, 5).join(', ') + (item.match_dates?.length > 5 ? '...' : ''),
    }
  })
})

const lastTaskId = computed(() => {
  if (!run.value?.steps_result?.length) return ''
  return run.value.steps_result[run.value.steps_result.length - 1].task_id
})

async function loadRun() {
  const { data } = await fetchRun(runId)
  run.value = data
}

async function doNextStep() {
  stepping.value = true
  try {
    await nextStep(runId)
    await loadRun()
  } finally {
    stepping.value = false
  }
}

async function pollRunStatus() {
  if (!run.value || isComplete.value) return
  try {
    const { data } = await fetchRunStatus(runId)
    if (data.status !== run.value.status) {
      await loadRun()
    }
    if (data.status === 'success' || data.status === 'failed') {
      clearInterval(pollTimer)
    }
  } catch {}
}

onMounted(async () => {
  await loadRun()
  if (!isComplete.value) {
    pollTimer = setInterval(pollRunStatus, 3000)
  }
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.run-detail-page { padding: 20px; max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
.page-header h1 { margin: 0; }
.run-meta { font-size: 13px; color: #909399; }
.btn-back { background: none; border: none; color: #409eff; cursor: pointer; font-size: 14px; }
.steps-flow { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.step-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px 16px; cursor: pointer; min-width: 120px; transition: all 0.2s; }
.step-card:hover { border-color: #409eff; }
.step-card.active { border-color: #409eff; background: #ecf5ff; }
.step-header { display: flex; flex-direction: column; gap: 4px; }
.step-num { font-size: 14px; font-weight: 600; color: #303133; }
.step-io { font-size: 12px; color: #909399; }
.step-symbols { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; max-height: 100px; overflow-y: auto; }
.symbol-tag { padding: 2px 8px; background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 3px; font-size: 12px; cursor: pointer; }
.symbol-tag:hover { background: #409eff; color: white; }
.next-step-section { display: flex; align-items: center; }
.btn-primary { padding: 8px 16px; background: #409eff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn-primary:disabled { background: #c0c4cc; cursor: not-allowed; }
.running-msg { color: #e6a23c; font-size: 14px; }
.error-msg { color: #f56c6c; font-size: 14px; padding: 8px 12px; background: #ffebee; border-radius: 4px; }
.final-result { margin-top: 24px; }
.final-result h2 { font-size: 16px; color: #303133; margin-bottom: 12px; }
.result-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.result-table th { background: #f5f7fa; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }
.result-table td { padding: 8px 12px; border-bottom: 1px solid #ebeef5; }
.result-table a { color: #409eff; cursor: pointer; }
.view-btn { padding: 6px 14px; background: #67c23a; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.loading { color: #909399; font-size: 14px; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/RunDetail.vue
git commit -m "feat: add run detail page with step-by-step view"
```

---

### Task 11: 删除旧页面 + 全量集成测试

**Files:**
- Delete: `frontend/src/views/ScreenerPage.vue` (keep as backup or remove reference)
- Modify: `frontend/src/views/BacktestPage.vue` (redirect or remove)

- [ ] **Step 1: 保留旧 BacktestPage.vue 作为兼容重定向**

将 `frontend/src/views/BacktestPage.vue` 替换为简单的重定向组件（如果有直接链接到 `/backtest` 的老 URL，它们现在由 StrategyGroupList 接管，BacktestPage 不再需要）。

由于路由已经在 Task 5 中将 `/backtest` 指向 `StrategyGroupList.vue`，只需确认删除旧路由引用。如果 `BacktestPage.vue` 不再被引用，可保留文件不动（不会被加载）。

- [ ] **Step 2: 运行全量后端测试**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 3: 运行前端构建验证**

Run: `cd frontend && npm run build`
Expected: Build succeeds without errors

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: complete strategy group feature integration"
```

---

## Summary of Tasks

| # | Task | 说明 |
|---|------|------|
| 1 | 数据库建表 + GroupManager CRUD | SQLite 新表 + 基础增删改查 |
| 2 | 策略组执行引擎 | GroupRunner: 一键/逐步执行 |
| 3 | API 路由 | FastAPI endpoints |
| 4 | 历史迁移 | source_task_id 链路转策略组 |
| 5 | 前端 API + 路由 | axios 函数 + vue-router |
| 6 | 策略调试页 | StrategyDebug.vue (原 ScreenerPage) |
| 7 | 策略组列表页 | StrategyGroupList.vue |
| 8 | 创建/编辑页 | StrategyGroupEdit.vue |
| 9 | 运行历史页 | StrategyGroupDetail.vue |
| 10 | 运行详情页 | RunDetail.vue |
| 11 | 集成验证 | 删旧文件 + 全量测试 |
