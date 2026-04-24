# 估值数据获取与存储 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为全部A股拉取5个估值指标的历史数据并存储为parquet，支持全量拉取和增量更新。

**Architecture:** 新增 `valuation_updater.py` 服务处理数据拉取逻辑，新增 `routers/valuation.py` 提供API触发入口，前端 UpdateStatus.vue 增加估值更新按钮。采用与 `data_updater.py` 相同的后台线程+进度报告模式。

**Tech Stack:** Python, AKShare (`stock_zh_valuation_baidu`), pandas, parquet, FastAPI, Vue 3

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/config.py` | Modify | 新增 `VALUATION_DIR` 常量 |
| `backend/services/valuation_updater.py` | Create | 核心拉取逻辑：全量/增量、断点续传、进度报告 |
| `backend/routers/valuation.py` | Create | API路由：触发更新、查询状态 |
| `backend/main.py` | Modify | 注册 valuation router |
| `backend/tests/test_valuation_updater.py` | Create | 服务层单元测试（mock AKShare） |
| `backend/tests/test_valuation_api.py` | Create | API层测试 |
| `frontend/src/api/index.js` | Modify | 新增估值更新API调用 |
| `frontend/src/components/UpdateStatus.vue` | Modify | 新增估值数据更新按钮和状态 |

---

### Task 1: 新增 VALUATION_DIR 配置

**Files:**
- Modify: `backend/config.py`

- [ ] **Step 1: 添加配置常量**

在 `config.py` 的 `QFQ_KLINE_DIR` 行后添加：

```python
VALUATION_DIR = DATA_DIR / "valuation" / "A"
```

在 `LOG_DIR.mkdir(...)` 行后添加：

```python
VALUATION_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: 验证**

Run: `python -c "import sys; sys.path.insert(0,'backend'); from config import VALUATION_DIR; print(VALUATION_DIR)"`
Expected: 输出路径 `...data/valuation/A`

- [ ] **Step 3: Commit**

```bash
git add backend/config.py
git commit -m "feat: add VALUATION_DIR config"
```

---

### Task 2: 实现 valuation_updater.py 核心逻辑

**Files:**
- Create: `backend/services/valuation_updater.py`
- Test: `backend/tests/test_valuation_updater.py`

- [ ] **Step 1: 编写测试文件**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from services.valuation_updater import (
    INDICATOR_MAP,
    fetch_single_indicator,
    fetch_symbol_valuation,
    run_valuation_update,
)


@pytest.fixture
def tmp_valuation_dir(tmp_path):
    return tmp_path


def _mock_baidu_response(dates, values):
    return pd.DataFrame({"date": dates, "value": values})


class TestFetchSingleIndicator:
    @patch("services.valuation_updater.ak.stock_zh_valuation_baidu")
    def test_returns_renamed_series(self, mock_api):
        mock_api.return_value = _mock_baidu_response(
            ["2024-01-01", "2024-01-18"], [10.5, 11.2]
        )
        result = fetch_single_indicator("000001", "市盈率(TTM)", "pe_ttm", "全部")
        assert list(result.columns) == ["date", "pe_ttm"]
        assert len(result) == 2
        mock_api.assert_called_once_with(symbol="000001", indicator="市盈率(TTM)", period="全部")

    @patch("services.valuation_updater.ak.stock_zh_valuation_baidu")
    def test_api_failure_returns_none(self, mock_api):
        mock_api.side_effect = Exception("timeout")
        result = fetch_single_indicator("000001", "市盈率(TTM)", "pe_ttm", "全部")
        assert result is None


class TestFetchSymbolValuation:
    @patch("services.valuation_updater.fetch_single_indicator")
    def test_merges_all_indicators(self, mock_fetch):
        dates = ["2024-01-01", "2024-01-18"]
        def side_effect(symbol, indicator, col_name, period):
            return pd.DataFrame({"date": dates, col_name: [1.0, 2.0]})
        mock_fetch.side_effect = side_effect
        result = fetch_symbol_valuation("000001", "全部")
        assert result is not None
        assert set(result.columns) == {"date", "total_mv", "pe_ttm", "pe_static", "pb", "pcf"}
        assert len(result) == 2

    @patch("services.valuation_updater.fetch_single_indicator")
    def test_all_fail_returns_none(self, mock_fetch):
        mock_fetch.return_value = None
        result = fetch_symbol_valuation("000001", "全部")
        assert result is None

    @patch("services.valuation_updater.fetch_single_indicator")
    def test_partial_fail_still_merges(self, mock_fetch):
        dates = ["2024-01-01", "2024-01-18"]
        def side_effect(symbol, indicator, col_name, period):
            if col_name == "pcf":
                return None
            return pd.DataFrame({"date": dates, col_name: [1.0, 2.0]})
        mock_fetch.side_effect = side_effect
        result = fetch_symbol_valuation("000001", "全部")
        assert result is not None
        assert "pcf" not in result.columns
        assert "pe_ttm" in result.columns


class TestRunValuationUpdate:
    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_full_mode_creates_parquet(self, mock_fetch, tmp_valuation_dir):
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-01-18", "2024-01-01"],
            "total_mv": [100.0, 90.0],
            "pe_ttm": [15.0, 14.0],
            "pe_static": [16.0, 15.0],
            "pb": [2.0, 1.9],
            "pcf": [8.0, 7.5],
        })
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["success"] == 1
        assert result["failed"] == 0
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        assert pf.exists()
        df = pd.read_parquet(pf)
        assert df.iloc[0]["date"] == "2024-01-18"

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_full_mode_skips_existing(self, mock_fetch, tmp_valuation_dir):
        existing = pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [90.0], "pe_ttm": [14.0],
            "pe_static": [15.0], "pb": [1.9], "pcf": [7.5],
        })
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_full_mode_force_overwrites(self, mock_fetch, tmp_valuation_dir):
        existing = pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [90.0], "pe_ttm": [14.0],
            "pe_static": [15.0], "pb": [1.9], "pcf": [7.5],
        })
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-01-18", "2024-01-01"],
            "total_mv": [100.0, 90.0],
            "pe_ttm": [15.0, 14.0],
            "pe_static": [16.0, 15.0],
            "pb": [2.0, 1.9],
            "pcf": [8.0, 7.5],
        })
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir, force=True
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 2

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_incremental_appends_new_data(self, mock_fetch, tmp_valuation_dir):
        existing = pd.DataFrame({
            "date": ["2024-01-18", "2024-01-01"],
            "total_mv": [100.0, 90.0],
            "pe_ttm": [15.0, 14.0],
            "pe_static": [16.0, 15.0],
            "pb": [2.0, 1.9],
            "pcf": [8.0, 7.5],
        })
        pf = tmp_valuation_dir / "000001.SZ.parquet"
        existing.to_parquet(pf, index=False)
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-02-05", "2024-01-18", "2024-01-01"],
            "total_mv": [110.0, 100.0, 90.0],
            "pe_ttm": [16.0, 15.0, 14.0],
            "pe_static": [17.0, 16.0, 15.0],
            "pb": [2.1, 2.0, 1.9],
            "pcf": [8.5, 8.0, 7.5],
        })
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="incremental", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["success"] == 1
        df = pd.read_parquet(pf)
        assert len(df) == 3
        assert df.iloc[0]["date"] == "2024-02-05"

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_incremental_skips_no_existing(self, mock_fetch, tmp_valuation_dir):
        symbols = ["000001.SZ"]
        result = run_valuation_update(
            mode="incremental", symbols=symbols, valuation_dir=tmp_valuation_dir
        )
        assert result["skipped"] == 1
        mock_fetch.assert_not_called()

    @patch("services.valuation_updater.fetch_symbol_valuation")
    def test_progress_callback(self, mock_fetch, tmp_valuation_dir):
        mock_fetch.return_value = pd.DataFrame({
            "date": ["2024-01-01"],
            "total_mv": [90.0], "pe_ttm": [14.0],
            "pe_static": [15.0], "pb": [1.9], "pcf": [7.5],
        })
        progress_calls = []
        def on_progress(current, total, phase):
            progress_calls.append((current, total, phase))
        symbols = ["000001.SZ", "000002.SZ"]
        run_valuation_update(
            mode="full", symbols=symbols, valuation_dir=tmp_valuation_dir,
            on_progress=on_progress
        )
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == 2
        assert progress_calls[-1][1] == 2
```

- [ ] **Step 2: 运行测试确认全部失败**

Run: `python -m pytest backend/tests/test_valuation_updater.py -x -v`
Expected: 所有测试 FAIL（ImportError，模块不存在）

- [ ] **Step 3: 实现 valuation_updater.py**

```python
import time
import logging
from pathlib import Path
from typing import Callable, Optional

import akshare as ak
import pandas as pd

from config import VALUATION_DIR, QFQ_KLINE_DIR

logger = logging.getLogger(__name__)

INDICATOR_MAP = {
    "总市值": "total_mv",
    "市盈率(TTM)": "pe_ttm",
    "市盈率(静)": "pe_static",
    "市净率": "pb",
    "市现率": "pcf",
}

SLEEP_BETWEEN_CALLS = 0.3


def fetch_single_indicator(
    symbol: str, indicator: str, col_name: str, period: str
) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_valuation_baidu(symbol=symbol, indicator=indicator, period=period)
        df = df.rename(columns={"value": col_name})
        return df[["date", col_name]]
    except Exception as e:
        logger.warning(f"获取 {symbol} {indicator} 失败: {e}")
        return None


def fetch_symbol_valuation(symbol: str, period: str) -> pd.DataFrame | None:
    code = symbol.split(".")[0]
    dfs = []
    for indicator, col_name in INDICATOR_MAP.items():
        df = fetch_single_indicator(code, indicator, col_name, period)
        if df is not None:
            dfs.append(df)
        time.sleep(SLEEP_BETWEEN_CALLS)
    if not dfs:
        return None
    merged = dfs[0]
    for df in dfs[1:]:
        merged = merged.merge(df, on="date", how="outer")
    merged = merged.sort_values("date", ascending=False).reset_index(drop=True)
    return merged


def get_all_symbols() -> list[str]:
    return [f.stem for f in sorted(QFQ_KLINE_DIR.glob("*.parquet"))]


def run_valuation_update(
    mode: str = "full",
    symbols: list[str] | None = None,
    valuation_dir: Path | None = None,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    if valuation_dir is None:
        valuation_dir = VALUATION_DIR
    valuation_dir.mkdir(parents=True, exist_ok=True)

    if symbols is None:
        symbols = get_all_symbols()

    total = len(symbols)
    success = 0
    skipped = 0
    failed = 0
    errors = []

    for i, sym in enumerate(symbols, 1):
        filepath = valuation_dir / f"{sym}.parquet"

        if mode == "full":
            if filepath.exists() and not force:
                skipped += 1
                if on_progress:
                    on_progress(i, total, "拉取估值数据")
                continue
            df = fetch_symbol_valuation(sym, "全部")
            if df is None:
                failed += 1
                errors.append(sym)
            else:
                df.to_parquet(filepath, index=False)
                success += 1

        elif mode == "incremental":
            if not filepath.exists():
                skipped += 1
                if on_progress:
                    on_progress(i, total, "增量更新估值数据")
                continue
            existing = pd.read_parquet(filepath)
            latest_date = existing.iloc[0]["date"] if not existing.empty else ""
            new_df = fetch_symbol_valuation(sym, "近一年")
            if new_df is None:
                failed += 1
                errors.append(sym)
            else:
                new_rows = new_df[new_df["date"] > latest_date]
                if not new_rows.empty:
                    merged = pd.concat([new_rows, existing], ignore_index=True)
                    merged = merged.sort_values("date", ascending=False).reset_index(drop=True)
                    merged.to_parquet(filepath, index=False)
                success += 1

        if on_progress:
            phase = "拉取估值数据" if mode == "full" else "增量更新估值数据"
            on_progress(i, total, phase)

    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "total": total,
    }
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `python -m pytest backend/tests/test_valuation_updater.py -x -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/valuation_updater.py backend/tests/test_valuation_updater.py
git commit -m "feat: add valuation data fetcher with full/incremental modes"
```

---

### Task 3: 新增 valuation API 路由

**Files:**
- Create: `backend/routers/valuation.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_valuation_api.py`

- [ ] **Step 1: 编写测试文件**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestValuationAPI:
    @patch("routers.valuation.run_update_in_background")
    def test_trigger_full_update(self, mock_run):
        resp = client.post("/api/valuation/update", json={"mode": "full"})
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data or "message" in data
        mock_run.assert_called_once()

    @patch("routers.valuation.run_update_in_background")
    def test_trigger_incremental_update(self, mock_run):
        resp = client.post("/api/valuation/update", json={"mode": "incremental"})
        assert resp.status_code == 200
        mock_run.assert_called_once()

    def test_get_status_idle(self):
        resp = client.get("/api/valuation/update/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_valuation_api.py -x -v`
Expected: FAIL（router不存在）

- [ ] **Step 3: 实现 routers/valuation.py**

```python
import threading
from fastapi import APIRouter

from services.valuation_updater import run_valuation_update, get_all_symbols

router = APIRouter(prefix="/api/valuation", tags=["valuation"])

_status = {"status": "idle", "progress": None, "result": None}
_lock = threading.Lock()


def run_update_in_background(mode: str, force: bool = False):
    def _task():
        with _lock:
            _status["status"] = "running"
            _status["progress"] = None
            _status["result"] = None

        def on_progress(current, total, phase):
            _status["progress"] = {"current": current, "total": total, "phase": phase}

        try:
            result = run_valuation_update(mode=mode, force=force, on_progress=on_progress)
            _status["status"] = "success"
            _status["result"] = result
        except Exception as e:
            _status["status"] = "failed"
            _status["result"] = {"error": str(e)}

    t = threading.Thread(target=_task, daemon=True)
    t.start()


@router.post("/update")
def api_trigger_valuation_update(body: dict = None):
    body = body or {}
    mode = body.get("mode", "full")
    force = body.get("force", False)
    if _status["status"] == "running":
        return {"message": "already running"}
    run_update_in_background(mode, force)
    return {"message": "valuation update started", "mode": mode}


@router.get("/update/status")
def api_valuation_status():
    return dict(_status)
```

- [ ] **Step 4: 注册路由到 main.py**

在 `backend/main.py` 添加：

```python
from routers.valuation import router as valuation_router
```

在 `app.include_router(portfolio_router)` 后添加：

```python
app.include_router(valuation_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_valuation_api.py -x -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/valuation.py backend/main.py backend/tests/test_valuation_api.py
git commit -m "feat: add valuation update API endpoint"
```

---

### Task 4: 前端增加估值数据更新按钮

**Files:**
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/components/UpdateStatus.vue`

- [ ] **Step 1: 添加 API 函数**

在 `frontend/src/api/index.js` 的 `fetchUpdateLogs` 后添加：

```javascript
export function triggerValuationUpdate(mode = 'full', force = false) {
  return api.post('/valuation/update', { mode, force })
}

export function fetchValuationStatus() {
  return api.get('/valuation/update/status')
}
```

- [ ] **Step 2: 修改 UpdateStatus.vue**

新增估值更新区域，添加全量/增量按钮、进度显示：

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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { fetchUpdateStatus, triggerUpdate as apiTriggerUpdate, triggerValuationUpdate, fetchValuationStatus } from '../api'

const status = ref('idle')
const result = ref(null)
const targetDate = ref(new Date().toISOString().slice(0, 10))
let timer = null

const valStatus = ref('idle')
const valProgress = ref(null)
const valResult = ref(null)
let valTimer = null

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
      if (valTimer) {
        clearInterval(valTimer)
        valTimer = null
      }
    }
  } catch {}
}

async function triggerValUpdate(mode) {
  await triggerValuationUpdate(mode)
  valStatus.value = 'running'
  valProgress.value = null
  valResult.value = null
  if (!valTimer) {
    valTimer = setInterval(pollValStatus, 2000)
  }
}

onMounted(() => {
  pollStatus()
  pollValStatus()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (valTimer) clearInterval(valTimer)
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
git commit -m "feat: add valuation update UI with progress display"
```

---

### Task 5: 运行全部测试确认无回归

**Files:** None (verification only)

- [ ] **Step 1: 运行全部后端测试**

Run: `python -m pytest backend/tests/ -x -q`
Expected: 全部 PASS

- [ ] **Step 2: Commit（如有修复）**

仅在有修复时commit。
