# 历史分红数据获取与存储 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为全部A股拉取历史分红数据并存储为parquet，支持东方财富主数据源+新浪fallback，全量/增量更新。

**Architecture:** 新增 `dividend_updater.py` 服务处理数据拉取逻辑（含fallback和列映射），新增 `routers/dividend.py` 提供API入口，前端 UpdateStatus.vue 增加分红数据更新行。架构与 `valuation_updater.py` 保持一致。

**Tech Stack:** Python, AKShare (`stock_fhps_detail_em`, `stock_history_dividend_detail`), pandas, parquet, FastAPI, Vue 3

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/config.py` | Modify | 新增 `DIVIDEND_DIR` 常量 |
| `backend/services/dividend_updater.py` | Create | 核心拉取逻辑：东方财富+新浪fallback、列映射、全量/增量、断点续传、进度日志 |
| `backend/routers/dividend.py` | Create | API路由：触发更新、查询状态 |
| `backend/main.py` | Modify | 注册 dividend router |
| `backend/tests/test_dividend_updater.py` | Create | 服务层单元测试（mock AKShare） |
| `backend/tests/test_dividend_api.py` | Create | API层测试 |
| `frontend/src/api/index.js` | Modify | 新增分红更新API调用 |
| `frontend/src/components/UpdateStatus.vue` | Modify | 新增分红数据更新行 |

---

### Task 1: 新增 DIVIDEND_DIR 配置

**Files:**
- Modify: `backend/config.py`

- [ ] **Step 1: 添加配置常量**

在 `config.py` 的 `VALUATION_DIR` 行后添加：

```python
DIVIDEND_DIR = DATA_DIR / "dividend" / "A"
```

在 `VALUATION_DIR.mkdir(...)` 行后添加：

```python
DIVIDEND_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: 验证**

Run: `python -c "import sys; sys.path.insert(0,'backend'); from config import DIVIDEND_DIR; print(DIVIDEND_DIR)"`
Expected: 输出路径 `...data/dividend/A`

- [ ] **Step 3: Commit**

```bash
git add backend/config.py
git commit -m "feat: add DIVIDEND_DIR config"
```

---

### Task 2: 实现 dividend_updater.py 核心逻辑

**Files:**
- Create: `backend/services/dividend_updater.py`
- Test: `backend/tests/test_dividend_updater.py`

- [ ] **Step 1: 编写测试文件**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from services.dividend_updater import (
    EM_COLUMNS,
    SINA_TO_EM_MAP,
    fetch_dividend_em,
    fetch_dividend_sina,
    map_sina_to_em,
    fetch_symbol_dividend,
    run_dividend_update,
)


@pytest.fixture
def tmp_dividend_dir(tmp_path):
    return tmp_path


def _make_em_df():
    return pd.DataFrame({
        "报告期": ["2024-12-31", "2023-12-31"],
        "业绩披露日期": ["2025-03-15", "2024-03-15"],
        "送转股份-送转总比例": [0.0, 0.0],
        "送转股份-送股比例": [0.0, 0.0],
        "送转股份-转股比例": [0.0, 0.0],
        "现金分红-现金分红比例": [3.5, 2.8],
        "现金分红-现金分红比例描述": ["10派3.5元", "10派2.8元"],
        "现金分红-股息率": [0.02, 0.015],
        "每股收益": [1.5, 1.2],
        "每股净资产": [10.0, 9.5],
        "每股公积金": [3.0, 2.8],
        "每股未分配利润": [5.0, 4.5],
        "净利润同比增长": [0.1, 0.05],
        "总股本": [1000000.0, 1000000.0],
        "预案公告日": ["2025-03-20", "2024-03-20"],
        "股权登记日": ["2025-06-10", "2024-06-10"],
        "除权除息日": ["2025-06-11", "2024-06-11"],
        "方案进度": ["实施分配", "实施分配"],
        "最新公告日期": ["2025-03-20", "2024-03-20"],
    })


def _make_sina_df():
    return pd.DataFrame({
        "公告日期": ["2025-03-20", "2024-03-20"],
        "送股": [0.0, 0.0],
        "转增": [0.0, 0.0],
        "派息": [3.5, 2.8],
        "进度": ["实施", "实施"],
        "除权除息日": ["2025-06-11", "2024-06-11"],
        "股权登记日": ["2025-06-10", "2024-06-10"],
        "红股上市日": [None, None],
    })


class TestFetchDividendEm:
    @patch("services.dividend_updater._call_em_api")
    def test_returns_dataframe(self, mock_api):
        mock_api.return_value = _make_em_df()
        result = fetch_dividend_em("000001")
        assert result is not None
        assert len(result) == 2
        assert list(result.columns) == EM_COLUMNS
        mock_api.assert_called_once_with("000001")

    @patch("services.dividend_updater._call_em_api")
    def test_api_failure_returns_none(self, mock_api):
        mock_api.side_effect = Exception("timeout")
        result = fetch_dividend_em("000001")
        assert result is None


class TestFetchDividendSina:
    @patch("services.dividend_updater._call_sina_api")
    def test_returns_dataframe(self, mock_api):
        mock_api.return_value = _make_sina_df()
        result = fetch_dividend_sina("000001")
        assert result is not None
        assert len(result) == 2
        mock_api.assert_called_once_with("000001")

    @patch("services.dividend_updater._call_sina_api")
    def test_api_failure_returns_none(self, mock_api):
        mock_api.side_effect = Exception("timeout")
        result = fetch_dividend_sina("000001")
        assert result is None


class TestMapSinaToEm:
    def test_maps_columns_correctly(self):
        sina_df = _make_sina_df()
        result = map_sina_to_em(sina_df)
        assert list(result.columns) == EM_COLUMNS
        assert result.iloc[0]["现金分红-现金分红比例"] == 3.5
        assert result.iloc[0]["送转股份-送股比例"] == 0.0
        assert result.iloc[0]["送转股份-转股比例"] == 0.0
        assert result.iloc[0]["送转股份-送转总比例"] == 0.0
        assert result.iloc[0]["预案公告日"] == "2025-03-20"
        assert result.iloc[0]["方案进度"] == "实施"
        assert pd.isna(result.iloc[0]["每股收益"])

    def test_computes_total_ratio(self):
        sina_df = pd.DataFrame({
            "公告日期": ["2025-03-20"],
            "送股": [2.0],
            "转增": [3.0],
            "派息": [1.0],
            "进度": ["实施"],
            "除权除息日": ["2025-06-11"],
            "股权登记日": ["2025-06-10"],
            "红股上市日": [None],
        })
        result = map_sina_to_em(sina_df)
        assert result.iloc[0]["送转股份-送转总比例"] == 5.0
        assert result.iloc[0]["送转股份-送股比例"] == 2.0
        assert result.iloc[0]["送转股份-转股比例"] == 3.0


class TestFetchSymbolDividend:
    @patch("services.dividend_updater.fetch_dividend_em")
    def test_em_success(self, mock_em):
        mock_em.return_value = _make_em_df()
        result = fetch_symbol_dividend("000001.SZ")
        assert result is not None
        assert len(result) == 2
        mock_em.assert_called_once_with("000001")

    @patch("services.dividend_updater.fetch_dividend_sina")
    @patch("services.dividend_updater.fetch_dividend_em")
    def test_em_fail_fallback_sina(self, mock_em, mock_sina):
        mock_em.return_value = None
        mock_sina.return_value = _make_sina_df()
        result = fetch_symbol_dividend("000001.SZ")
        assert result is not None
        assert list(result.columns) == EM_COLUMNS

    @patch("services.dividend_updater.fetch_dividend_sina")
    @patch("services.dividend_updater.fetch_dividend_em")
    def test_both_fail_returns_none(self, mock_em, mock_sina):
        mock_em.return_value = None
        mock_sina.return_value = None
        result = fetch_symbol_dividend("000001.SZ")
        assert result is None


class TestRunDividendUpdate:
    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_full_mode_creates_parquet(self, mock_fetch, tmp_dividend_dir):
        mock_fetch.return_value = _make_em_df()
        symbols = ["000001.SZ"]
        result = run_dividend_update(
            mode="full", symbols=symbols, dividend_dir=tmp_dividend_dir
        )
        assert result["success"] == 1
        assert result["failed"] == 0
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        assert pf.exists()
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_full_mode_skips_existing(self, mock_fetch, tmp_dividend_dir):
        existing = _make_em_df()
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        result = run_dividend_update(
            mode="full", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_full_mode_force_overwrites(self, mock_fetch, tmp_dividend_dir):
        existing = _make_em_df().head(1)
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = _make_em_df()
        result = run_dividend_update(
            mode="full", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir, force=True
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_incremental_merges_new(self, mock_fetch, tmp_dividend_dir):
        existing = _make_em_df().tail(1)
        pf = tmp_dividend_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = _make_em_df()
        result = run_dividend_update(
            mode="incremental", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_incremental_skips_no_existing(self, mock_fetch, tmp_dividend_dir):
        result = run_dividend_update(
            mode="incremental", symbols=["000001.SZ"], dividend_dir=tmp_dividend_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.dividend_updater.fetch_symbol_dividend")
    def test_progress_callback(self, mock_fetch, tmp_dividend_dir):
        mock_fetch.return_value = _make_em_df()
        progress_calls = []
        def on_progress(current, total, phase):
            progress_calls.append((current, total, phase))
        run_dividend_update(
            mode="full", symbols=["000001.SZ", "000002.SZ"],
            dividend_dir=tmp_dividend_dir, on_progress=on_progress
        )
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == 2
        assert progress_calls[-1][1] == 2
```

- [ ] **Step 2: 运行测试确认全部失败**

Run: `python -m pytest backend/tests/test_dividend_updater.py -x -v`
Expected: 所有测试 FAIL（ImportError，模块不存在）

- [ ] **Step 3: 实现 dividend_updater.py**

```python
import time
import logging
from pathlib import Path
from typing import Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import akshare as ak
import pandas as pd

from config import DIVIDEND_DIR, QFQ_KLINE_DIR, LOG_DIR

logger = logging.getLogger(__name__)

EM_COLUMNS = [
    "报告期", "业绩披露日期", "送转股份-送转总比例", "送转股份-送股比例", "送转股份-转股比例",
    "现金分红-现金分红比例", "现金分红-现金分红比例描述", "现金分红-股息率",
    "每股收益", "每股净资产", "每股公积金", "每股未分配利润", "净利润同比增长", "总股本",
    "预案公告日", "股权登记日", "除权除息日", "方案进度", "最新公告日期",
]

SINA_TO_EM_MAP = {
    "送股": "送转股份-送股比例",
    "转增": "送转股份-转股比例",
    "派息": "现金分红-现金分红比例",
    "公告日期": "预案公告日",
    "股权登记日": "股权登记日",
    "除权除息日": "除权除息日",
    "进度": "方案进度",
}

SLEEP_BETWEEN_CALLS = 0.5
API_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_WAIT = 5

DIVIDEND_PROGRESS_FILE = LOG_DIR / "dividend_progress.log"


def _log_progress(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(DIVIDEND_PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _call_em_api(symbol: str) -> pd.DataFrame:
    return ak.stock_fhps_detail_em(symbol=symbol)


def _call_sina_api(symbol: str) -> pd.DataFrame:
    return ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")


def fetch_dividend_em(symbol: str) -> pd.DataFrame | None:
    for attempt in range(MAX_RETRIES):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_em_api, symbol)
                df = future.result(timeout=API_TIMEOUT)
            for col in EM_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            return df[EM_COLUMNS]
        except FutureTimeout:
            logger.warning(f"东方财富 {symbol} 超时 (第{attempt+1}次)")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            logger.warning(f"东方财富 {symbol} 失败 (第{attempt+1}次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
    return None


def fetch_dividend_sina(symbol: str) -> pd.DataFrame | None:
    for attempt in range(MAX_RETRIES):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_sina_api, symbol)
                df = future.result(timeout=API_TIMEOUT)
            return df
        except FutureTimeout:
            logger.warning(f"新浪 {symbol} 超时 (第{attempt+1}次)")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            logger.warning(f"新浪 {symbol} 失败 (第{attempt+1}次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
    return None


def map_sina_to_em(sina_df: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(columns=EM_COLUMNS)
    for sina_col, em_col in SINA_TO_EM_MAP.items():
        if sina_col in sina_df.columns:
            result[em_col] = sina_df[sina_col].values
    send = result["送转股份-送股比例"].fillna(0)
    transfer = result["送转股份-转股比例"].fillna(0)
    result["送转股份-送转总比例"] = send + transfer
    return result


def fetch_symbol_dividend(symbol: str) -> pd.DataFrame | None:
    code = symbol.split(".")[0]
    df = fetch_dividend_em(code)
    if df is not None:
        return df
    logger.info(f"{symbol} 东方财富失败, 尝试新浪fallback")
    sina_df = fetch_dividend_sina(code)
    if sina_df is not None:
        return map_sina_to_em(sina_df)
    return None


def get_all_symbols() -> list[str]:
    return [f.stem for f in sorted(QFQ_KLINE_DIR.glob("*.parquet"))]


def run_dividend_update(
    mode: str = "full",
    symbols: list[str] | None = None,
    dividend_dir: Path | None = None,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    if dividend_dir is None:
        dividend_dir = DIVIDEND_DIR
    dividend_dir.mkdir(parents=True, exist_ok=True)

    if symbols is None:
        symbols = get_all_symbols()

    total = len(symbols)
    success = 0
    skipped = 0
    failed = 0
    errors = []

    DIVIDEND_PROGRESS_FILE.write_text("", encoding="utf-8")
    _log_progress(f"开始{mode}更新分红数据, 共 {total} 只股票")

    for i, sym in enumerate(symbols, 1):
        filepath = dividend_dir / f"{sym}.parquet"

        if mode == "full":
            if filepath.exists() and not force:
                skipped += 1
                if on_progress:
                    on_progress(i, total, "拉取分红数据")
                continue
            df = fetch_symbol_dividend(sym)
            if df is None:
                failed += 1
                errors.append(sym)
                _log_progress(f"[失败] {sym}")
            else:
                df.to_parquet(filepath, index=False)
                success += 1

        elif mode == "incremental":
            if not filepath.exists():
                skipped += 1
                if on_progress:
                    on_progress(i, total, "增量更新分红数据")
                continue
            existing = pd.read_parquet(filepath)
            new_df = fetch_symbol_dividend(sym)
            if new_df is None:
                failed += 1
                errors.append(sym)
                _log_progress(f"[失败] {sym}")
            else:
                key_col = "报告期" if "报告期" in existing.columns else existing.columns[0]
                merged = pd.concat([new_df, existing], ignore_index=True)
                merged = merged.drop_duplicates(subset=[key_col], keep="first")
                merged = merged.sort_values(key_col, ascending=False).reset_index(drop=True)
                merged.to_parquet(filepath, index=False)
                success += 1

        if on_progress:
            phase = "拉取分红数据" if mode == "full" else "增量更新分红数据"
            on_progress(i, total, phase)

        if i % 100 == 0 or i == total:
            _log_progress(f"进度 {i}/{total} — 成功:{success} 跳过:{skipped} 失败:{failed}")

        time.sleep(SLEEP_BETWEEN_CALLS)

    _log_progress(f"完成! 成功:{success} 跳过:{skipped} 失败:{failed}")
    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "total": total,
    }
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `python -m pytest backend/tests/test_dividend_updater.py -x -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/dividend_updater.py backend/tests/test_dividend_updater.py
git commit -m "feat: add dividend data fetcher with EM primary + Sina fallback"
```

---

### Task 3: 新增 dividend API 路由

**Files:**
- Create: `backend/routers/dividend.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_dividend_api.py`

- [ ] **Step 1: 编写测试文件**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestDividendAPI:
    @patch("routers.dividend.run_update_in_background")
    def test_trigger_full_update(self, mock_run):
        resp = client.post("/api/dividend/update", json={"mode": "full"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "dividend update started"
        assert data["mode"] == "full"
        mock_run.assert_called_once_with("full", False)

    @patch("routers.dividend.run_update_in_background")
    def test_trigger_incremental_update(self, mock_run):
        resp = client.post("/api/dividend/update", json={"mode": "incremental"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "incremental"
        mock_run.assert_called_once_with("incremental", False)

    @patch("routers.dividend.run_update_in_background")
    def test_trigger_with_force(self, mock_run):
        resp = client.post("/api/dividend/update", json={"mode": "full", "force": True})
        assert resp.status_code == 200
        mock_run.assert_called_once_with("full", True)

    def test_get_status_idle(self):
        resp = client.get("/api/dividend/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    @patch("routers.dividend._status", {"status": "running", "progress": {"current": 10, "total": 200, "phase": "拉取分红数据"}, "result": None})
    def test_get_status_running(self):
        resp = client.get("/api/dividend/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["progress"]["current"] == 10
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_dividend_api.py -x -v`
Expected: FAIL

- [ ] **Step 3: 实现 routers/dividend.py**

```python
import threading
from fastapi import APIRouter

from services.dividend_updater import run_dividend_update

router = APIRouter(prefix="/api/dividend", tags=["dividend"])

_status = {"status": "idle", "progress": None, "result": None}
_lock = threading.Lock()


def run_update_in_background(mode: str, force: bool = False):
    def _task():
        _status["status"] = "running"
        _status["progress"] = None
        _status["result"] = None

        def on_progress(current, total, phase):
            _status["progress"] = {"current": current, "total": total, "phase": phase}

        try:
            result = run_dividend_update(mode=mode, force=force, on_progress=on_progress)
            _status["status"] = "success"
            _status["result"] = result
        except Exception as e:
            _status["status"] = "failed"
            _status["result"] = {"error": str(e)}

    t = threading.Thread(target=_task, daemon=True)
    t.start()


@router.post("/update")
def api_trigger_dividend_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    force = body.get("force", False)
    if _status["status"] == "running":
        return {"message": "already running"}
    run_update_in_background(mode, force)
    return {"message": "dividend update started", "mode": mode}


@router.get("/update/status")
def api_dividend_status():
    return dict(_status)
```

- [ ] **Step 4: 注册路由到 main.py**

在 `backend/main.py` 添加 import：

```python
from routers.dividend import router as dividend_router
```

在 `app.include_router(valuation_router)` 后添加：

```python
app.include_router(dividend_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_dividend_api.py -x -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/dividend.py backend/main.py backend/tests/test_dividend_api.py
git commit -m "feat: add dividend update API endpoint"
```

---

### Task 4: 前端增加分红数据更新按钮

**Files:**
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/components/UpdateStatus.vue`

- [ ] **Step 1: 添加 API 函数**

在 `frontend/src/api/index.js` 的 `fetchValuationStatus` 后添加：

```javascript
export function triggerDividendUpdate(mode = 'full', force = false) {
  return api.post('/dividend/update', { mode, force })
}

export function fetchDividendStatus() {
  return api.get('/dividend/update/status')
}
```

- [ ] **Step 2: 修改 UpdateStatus.vue**

在估值数据区域后新增分红数据区域，完整模板：

```vue
<template>
  <div class="update-status">
    <div class="status-row">
      <span class="status-label">行情数据:</span>
      <span :class="['status-badge', statusClass]">{{ statusText }}</span>
      <label class="date-pick">日期: <input type="date" v-model="targetDate" :disabled="status === 'running'" /></label>
      <button :disabled="status === 'running'" @click="triggerUpdate">
        {{ status === 'running' ? '更新中...' : '立即更新' }}
      </button>
    </div>
    <div v-if="result" class="status-detail">
      <span>成功: {{ result.updated }}</span>
      <span>跳过: {{ result.skipped }}</span>
      <span>失败: {{ result.failed }}</span>
      <span>新增: {{ result.new_stocks }}</span>
      <span v-if="result.finished_at">完成于: {{ result.finished_at }}</span>
    </div>

    <div class="status-row" style="margin-top: 12px;">
      <span class="status-label">估值数据:</span>
      <span :class="['status-badge', valStatusClass]">{{ valStatusText }}</span>
      <button :disabled="valStatus === 'running'" @click="triggerValUpdate('full')">全量拉取</button>
      <button :disabled="valStatus === 'running'" @click="triggerValUpdate('incremental')">增量更新</button>
    </div>
    <div v-if="valProgress && valStatus === 'running'" class="status-detail">
      <span>{{ valProgress.phase }}: {{ valProgress.current }}/{{ valProgress.total }}</span>
      <span>({{ Math.round(valProgress.current / valProgress.total * 100) }}%)</span>
    </div>
    <div v-if="valResult && valStatus !== 'running'" class="status-detail">
      <span>成功: {{ valResult.success }}</span>
      <span>跳过: {{ valResult.skipped }}</span>
      <span>失败: {{ valResult.failed }}</span>
    </div>

    <div class="status-row" style="margin-top: 12px;">
      <span class="status-label">分红数据:</span>
      <span :class="['status-badge', divStatusClass]">{{ divStatusText }}</span>
      <button :disabled="divStatus === 'running'" @click="triggerDivUpdate('full')">全量拉取</button>
      <button :disabled="divStatus === 'running'" @click="triggerDivUpdate('incremental')">增量更新</button>
    </div>
    <div v-if="divProgress && divStatus === 'running'" class="status-detail">
      <span>{{ divProgress.phase }}: {{ divProgress.current }}/{{ divProgress.total }}</span>
      <span>({{ Math.round(divProgress.current / divProgress.total * 100) }}%)</span>
    </div>
    <div v-if="divResult && divStatus !== 'running'" class="status-detail">
      <span>成功: {{ divResult.success }}</span>
      <span>跳过: {{ divResult.skipped }}</span>
      <span>失败: {{ divResult.failed }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  fetchUpdateStatus, triggerUpdate as apiTriggerUpdate,
  triggerValuationUpdate, fetchValuationStatus,
  triggerDividendUpdate, fetchDividendStatus
} from '../api'

const status = ref('idle')
const result = ref(null)
const targetDate = ref(new Date().toISOString().slice(0, 10))
let timer = null

const valStatus = ref('idle')
const valProgress = ref(null)
const valResult = ref(null)
let valTimer = null

const divStatus = ref('idle')
const divProgress = ref(null)
const divResult = ref(null)
let divTimer = null

const statusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[status.value] || status.value
})
const statusClass = computed(() => status.value)

const valStatusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[valStatus.value] || valStatus.value
})
const valStatusClass = computed(() => valStatus.value)

const divStatusText = computed(() => {
  const map = { idle: '空闲', running: '进行中', success: '成功', failed: '失败' }
  return map[divStatus.value] || divStatus.value
})
const divStatusClass = computed(() => divStatus.value)

async function pollStatus() {
  try {
    const { data } = await fetchUpdateStatus()
    status.value = data.status
    result.value = data.result
  } catch {}
}

async function triggerUpdate() {
  await apiTriggerUpdate(targetDate.value || undefined)
  status.value = 'running'
  if (!timer) {
    timer = setInterval(pollStatus, 2000)
  }
}

async function pollValStatus() {
  try {
    const { data } = await fetchValuationStatus()
    valStatus.value = data.status
    valProgress.value = data.progress
    if (data.status !== 'running') {
      valResult.value = data.result
      if (valTimer) { clearInterval(valTimer); valTimer = null }
    }
  } catch {}
}

async function triggerValUpdate(mode) {
  await triggerValuationUpdate(mode)
  valStatus.value = 'running'
  valProgress.value = null
  valResult.value = null
  if (!valTimer) { valTimer = setInterval(pollValStatus, 2000) }
}

async function pollDivStatus() {
  try {
    const { data } = await fetchDividendStatus()
    divStatus.value = data.status
    divProgress.value = data.progress
    if (data.status !== 'running') {
      divResult.value = data.result
      if (divTimer) { clearInterval(divTimer); divTimer = null }
    }
  } catch {}
}

async function triggerDivUpdate(mode) {
  await triggerDividendUpdate(mode)
  divStatus.value = 'running'
  divProgress.value = null
  divResult.value = null
  if (!divTimer) { divTimer = setInterval(pollDivStatus, 2000) }
}

onMounted(() => {
  pollStatus()
  pollValStatus()
  pollDivStatus()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (valTimer) clearInterval(valTimer)
  if (divTimer) clearInterval(divTimer)
})
</script>

<style scoped>
.update-status { padding: 12px; background: #f5f7fa; border-radius: 6px; margin-bottom: 16px; }
.status-row { display: flex; align-items: center; gap: 12px; }
.status-label { font-weight: bold; }
.status-badge { padding: 2px 8px; border-radius: 4px; font-size: 13px; }
.status-badge.idle { background: #e0e0e0; }
.status-badge.running { background: #fff3e0; color: #e65100; }
.status-badge.success { background: #e8f5e9; color: #2e7d32; }
.status-badge.failed { background: #ffebee; color: #c62828; }
.status-detail { margin-top: 8px; font-size: 13px; display: flex; gap: 16px; color: #666; }
.date-pick { font-size: 13px; }
.date-pick input { padding: 4px 8px; border: 1px solid #dcdfe6; border-radius: 4px; margin-left: 4px; }
button { padding: 6px 16px; cursor: pointer; border: 1px solid #dcdfe6; border-radius: 4px; background: white; }
button:disabled { cursor: not-allowed; opacity: 0.5; }
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/index.js frontend/src/components/UpdateStatus.vue
git commit -m "feat: add dividend update UI with progress display"
```

---

### Task 5: 运行全部测试确认无回归

**Files:** None (verification only)

- [ ] **Step 1: 运行全部后端测试**

Run: `python -m pytest backend/tests/ -x -q`
Expected: 全部 PASS
