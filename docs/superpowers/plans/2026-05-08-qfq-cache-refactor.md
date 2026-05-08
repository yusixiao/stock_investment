# QFQ 缓存重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 qfq 数据从独立源数据改为基于 raw + dividend 计算的缓存，支持增量追加和除权失效重算。

**Architecture:** 新增 `services/qfq_cache.py` 作为 qfq 数据唯一入口，内部管理缓存有效性。所有原先直接读 `QFQ_KLINE_DIR` 的地方统一改为调用此模块。

**Tech Stack:** Python, pandas, parquet, JSON (meta file)

---

### Task 1: 实现复权因子计算核心逻辑

**Files:**
- Create: `backend/services/qfq_cache.py`
- Create: `backend/tests/test_qfq_cache.py`

- [ ] **Step 1: Write the failing test — compute_qfq 基本计算**

```python
import pandas as pd
import numpy as np
from unittest.mock import patch
from services.qfq_cache import compute_qfq


class TestComputeQfq:
    def test_no_dividend(self):
        raw_df = pd.DataFrame({
            "date": ["2025-01-02", "2025-01-03", "2025-01-06"],
            "open": [10.0, 10.5, 11.0],
            "high": [10.5, 11.0, 11.5],
            "low": [9.5, 10.0, 10.5],
            "close": [10.5, 11.0, 11.5],
            "volume": [1000.0, 1100.0, 1200.0],
            "amount": [10000.0, 11000.0, 12000.0],
        })
        dividend_df = pd.DataFrame(columns=[
            "报告期", "送转股份-送股比例", "送转股份-转股比例",
            "现金分红-现金分红比例", "除权除息日", "方案进度",
        ])
        result = compute_qfq(raw_df, dividend_df)
        pd.testing.assert_frame_equal(result, raw_df)

    def test_single_dividend(self):
        raw_df = pd.DataFrame({
            "date": ["2025-06-11", "2025-06-12", "2025-06-13"],
            "open": [10.0, 9.5, 9.6],
            "high": [10.2, 9.7, 9.8],
            "low": [9.8, 9.3, 9.4],
            "close": [10.0, 9.5, 9.6],
            "volume": [1000.0, 1100.0, 1200.0],
            "amount": [10000.0, 11000.0, 12000.0],
        })
        dividend_df = pd.DataFrame({
            "报告期": ["2024-12-31"],
            "送转股份-送股比例": [0.0],
            "送转股份-转股比例": [0.0],
            "现金分红-现金分红比例": [5.0],
            "除权除息日": ["2025-06-12"],
            "方案进度": ["实施分配"],
        })
        result = compute_qfq(raw_df, dividend_df)
        pre_close = 10.0
        factor = (pre_close - 0.5) / pre_close
        assert abs(result.iloc[0]["close"] - 10.0 * factor) < 0.001
        assert abs(result.iloc[1]["close"] - 9.5) < 0.001
        assert abs(result.iloc[2]["close"] - 9.6) < 0.001

    def test_dividend_with_bonus_shares(self):
        raw_df = pd.DataFrame({
            "date": ["2025-06-11", "2025-06-12", "2025-06-13"],
            "open": [10.0, 6.0, 6.1],
            "high": [10.2, 6.2, 6.3],
            "low": [9.8, 5.8, 5.9],
            "close": [10.0, 6.0, 6.1],
            "volume": [1000.0, 1100.0, 1200.0],
            "amount": [10000.0, 11000.0, 12000.0],
        })
        dividend_df = pd.DataFrame({
            "报告期": ["2024-12-31"],
            "送转股份-送股比例": [5.0],
            "送转股份-转股比例": [0.0],
            "现金分红-现金分红比例": [5.0],
            "除权除息日": ["2025-06-12"],
            "方案进度": ["实施分配"],
        })
        result = compute_qfq(raw_df, dividend_df)
        pre_close = 10.0
        factor = (pre_close - 0.5) / (pre_close * (1 + 0.5))
        assert abs(result.iloc[0]["close"] - 10.0 * factor) < 0.001
        assert abs(result.iloc[1]["close"] - 6.0) < 0.001

    def test_multiple_dividends(self):
        raw_df = pd.DataFrame({
            "date": ["2025-01-10", "2025-06-12", "2025-10-15", "2025-10-16"],
            "open": [10.0, 9.0, 8.0, 8.1],
            "high": [10.5, 9.5, 8.5, 8.6],
            "low": [9.5, 8.5, 7.5, 7.6],
            "close": [10.0, 9.0, 8.0, 8.1],
            "volume": [1000.0, 1100.0, 1200.0, 1300.0],
            "amount": [10000.0, 11000.0, 12000.0, 13000.0],
        })
        dividend_df = pd.DataFrame({
            "报告期": ["2024-12-31", "2025-06-30"],
            "送转股份-送股比例": [0.0, 0.0],
            "送转股份-转股比例": [0.0, 0.0],
            "现金分红-现金分红比例": [3.0, 2.0],
            "除权除息日": ["2025-06-12", "2025-10-15"],
            "方案进度": ["实施分配", "实施分配"],
        })
        result = compute_qfq(raw_df, dividend_df)
        factor2 = (9.0 - 0.2) / 9.0
        factor1 = (10.0 - 0.3) / 10.0
        cum_factor_before_both = factor1 * factor2
        assert abs(result.iloc[0]["close"] - 10.0 * cum_factor_before_both) < 0.001
        assert abs(result.iloc[1]["close"] - 9.0 * factor2) < 0.001
        assert abs(result.iloc[2]["close"] - 8.0) < 0.001
        assert abs(result.iloc[3]["close"] - 8.1) < 0.001

    def test_filters_only_implemented(self):
        raw_df = pd.DataFrame({
            "date": ["2025-06-11", "2025-06-12"],
            "open": [10.0, 9.5],
            "high": [10.2, 9.7],
            "low": [9.8, 9.3],
            "close": [10.0, 9.5],
            "volume": [1000.0, 1100.0],
            "amount": [10000.0, 11000.0],
        })
        dividend_df = pd.DataFrame({
            "报告期": ["2024-12-31", "2025-12-31"],
            "送转股份-送股比例": [0.0, 0.0],
            "送转股份-转股比例": [0.0, 0.0],
            "现金分红-现金分红比例": [5.0, 3.0],
            "除权除息日": ["2025-06-12", None],
            "方案进度": ["实施分配", "董事会决议通过"],
        })
        result = compute_qfq(raw_df, dividend_df)
        pre_close = 10.0
        factor = (pre_close - 0.5) / pre_close
        assert abs(result.iloc[0]["close"] - 10.0 * factor) < 0.001
        assert abs(result.iloc[1]["close"] - 9.5) < 0.001
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_qfq_cache.py -x -v`
Expected: FAIL with "ModuleNotFoundError" or "ImportError"

- [ ] **Step 3: Write minimal implementation**

Create `backend/services/qfq_cache.py`:

```python
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from config import RAW_KLINE_DIR, QFQ_KLINE_DIR, DIVIDEND_DIR

QFQ_META_FILE = QFQ_KLINE_DIR / "_meta.json"


def _load_meta() -> dict:
    if QFQ_META_FILE.exists():
        return json.loads(QFQ_META_FILE.read_text(encoding="utf-8"))
    return {}


def _save_meta(meta: dict):
    QFQ_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    QFQ_META_FILE.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _get_implemented_dividends(dividend_df: pd.DataFrame) -> pd.DataFrame:
    if dividend_df.empty:
        return dividend_df
    mask = dividend_df["方案进度"].str.contains("实施", na=False)
    mask &= dividend_df["除权除息日"].notna()
    mask &= dividend_df["除权除息日"].astype(str) != ""
    mask &= dividend_df["除权除息日"].astype(str) != "None"
    return dividend_df[mask].copy()


def compute_qfq(raw_df: pd.DataFrame, dividend_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df.copy()

    impl = _get_implemented_dividends(dividend_df)
    if impl.empty:
        return raw_df.copy()

    asc = raw_df.sort_values("date").reset_index(drop=True)
    dates = asc["date"].values
    factors = np.ones(len(asc), dtype=np.float64)

    for _, row in impl.iterrows():
        ex_date = str(row["除权除息日"])
        cash = float(row.get("现金分红-现金分红比例", 0) or 0) / 10.0
        bonus = float(row.get("送转股份-送股比例", 0) or 0) / 10.0
        convert = float(row.get("送转股份-转股比例", 0) or 0) / 10.0

        pre_idx = np.where(dates < ex_date)[0]
        if len(pre_idx) == 0:
            continue
        pre_close_idx = pre_idx[-1]
        pre_close = float(asc.iloc[pre_close_idx]["close"])
        if pre_close == 0:
            continue

        single_factor = (pre_close - cash) / (pre_close * (1 + bonus + convert))

        mask = dates < ex_date
        factors[mask] *= single_factor

    result = asc.copy()
    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        result[col] = asc[col] * factors

    is_desc = raw_df.iloc[0]["date"] > raw_df.iloc[-1]["date"] if len(raw_df) > 1 else False
    if is_desc:
        result = result.sort_values("date", ascending=False).reset_index(drop=True)

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_qfq_cache.py -x -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/qfq_cache.py backend/tests/test_qfq_cache.py
git commit -m "feat: 实现 compute_qfq 复权因子计算核心逻辑"
```

---

### Task 2: 验证计算正确性 — 对比 qfq_validation

**Files:**
- Create: `backend/tests/test_qfq_validation.py`

- [ ] **Step 1: 重命名现有 qfq 目录为 qfq_validation**

```bash
mv data/kline/A/qfq data/kline/A/qfq_validation
mkdir -p data/kline/A/qfq
```

- [ ] **Step 2: Write validation test**

```python
import random
import pandas as pd
import numpy as np
import pytest
from pathlib import Path

from config import RAW_KLINE_DIR, DIVIDEND_DIR

BASE_DIR = Path(__file__).resolve().parent.parent.parent
QFQ_VALIDATION_DIR = BASE_DIR / "data" / "kline" / "A" / "qfq_validation"

DATA_AVAILABLE = QFQ_VALIDATION_DIR.exists() and any(QFQ_VALIDATION_DIR.glob("*.parquet"))
skip_no_data = pytest.mark.skipif(not DATA_AVAILABLE, reason="qfq_validation data not available")


def get_random_symbols(n=30):
    files = list(QFQ_VALIDATION_DIR.glob("*.parquet"))
    random.seed(42)
    selected = random.sample(files, min(n, len(files)))
    return [f.stem for f in selected]


@skip_no_data
class TestQfqValidation:
    @pytest.fixture(scope="class")
    def symbols(self):
        return get_random_symbols(30)

    def test_qfq_matches_validation(self, symbols):
        from services.qfq_cache import compute_qfq

        mismatches = []
        for symbol in symbols:
            raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
            div_path = DIVIDEND_DIR / f"{symbol}.parquet"
            val_path = QFQ_VALIDATION_DIR / f"{symbol}.parquet"

            if not raw_path.exists() or not val_path.exists():
                continue

            raw_df = pd.read_parquet(raw_path)
            div_df = pd.read_parquet(div_path) if div_path.exists() else pd.DataFrame()
            val_df = pd.read_parquet(val_path)

            computed = compute_qfq(raw_df, div_df)
            computed_asc = computed.sort_values("date").reset_index(drop=True)
            val_asc = val_df.sort_values("date").reset_index(drop=True)

            common_dates = set(computed_asc["date"]) & set(val_asc["date"])
            if not common_dates:
                continue

            comp_filtered = computed_asc[computed_asc["date"].isin(common_dates)].reset_index(drop=True)
            val_filtered = val_asc[val_asc["date"].isin(common_dates)].reset_index(drop=True)

            for col in ["open", "high", "low", "close"]:
                diff = np.abs(comp_filtered[col].values - val_filtered[col].values)
                max_diff = diff.max()
                if max_diff > 0.02:
                    mismatches.append(f"{symbol} col={col} max_diff={max_diff:.4f}")
                    break

        assert len(mismatches) == 0, f"Mismatches found:\n" + "\n".join(mismatches)
```

- [ ] **Step 3: Run validation test**

Run: `python -m pytest backend/tests/test_qfq_validation.py -x -v -s`
Expected: PASS — 30 只股票计算结果与 qfq_validation 一致（误差 < 0.02）

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_qfq_validation.py
git commit -m "test: 添加 qfq 计算正确性验证测试（对比 qfq_validation）"
```

---

### Task 3: 实现缓存管理逻辑（get_qfq_kline / invalidate）

**Files:**
- Modify: `backend/services/qfq_cache.py`
- Modify: `backend/tests/test_qfq_cache.py`

- [ ] **Step 1: Write failing tests for cache logic**

追加到 `backend/tests/test_qfq_cache.py`：

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from services.qfq_cache import get_qfq_kline, invalidate_cache, get_latest_ex_date


class TestCacheManagement:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.raw_dir = Path(self.tmp) / "raw"
        self.qfq_dir = Path(self.tmp) / "qfq"
        self.div_dir = Path(self.tmp) / "dividend"
        self.raw_dir.mkdir(parents=True)
        self.qfq_dir.mkdir(parents=True)
        self.div_dir.mkdir(parents=True)

        self.raw_df = pd.DataFrame({
            "date": ["2025-06-13", "2025-06-12", "2025-06-11"],
            "open": [9.6, 9.5, 10.0],
            "high": [9.8, 9.7, 10.2],
            "low": [9.4, 9.3, 9.8],
            "close": [9.6, 9.5, 10.0],
            "volume": [1200.0, 1100.0, 1000.0],
            "amount": [12000.0, 11000.0, 10000.0],
        })
        self.raw_df.to_parquet(self.raw_dir / "000001.SZ.parquet", index=False)

        self.div_df = pd.DataFrame({
            "报告期": ["2024-12-31"],
            "送转股份-送股比例": [0.0],
            "送转股份-转股比例": [0.0],
            "现金分红-现金分红比例": [5.0],
            "除权除息日": ["2025-06-12"],
            "方案进度": ["实施分配"],
        })
        self.div_df.to_parquet(self.div_dir / "000001.SZ.parquet", index=False)

    @patch("services.qfq_cache.RAW_KLINE_DIR")
    @patch("services.qfq_cache.QFQ_KLINE_DIR")
    @patch("services.qfq_cache.DIVIDEND_DIR")
    def test_get_qfq_kline_computes_and_caches(self, mock_div, mock_qfq, mock_raw):
        mock_raw.__truediv__ = lambda s, x: self.raw_dir / x
        mock_qfq.__truediv__ = lambda s, x: self.qfq_dir / x
        mock_div.__truediv__ = lambda s, x: self.div_dir / x
        mock_qfq.exists = lambda: True
        mock_qfq.parent = self.qfq_dir

        with patch("services.qfq_cache.QFQ_META_FILE", self.qfq_dir / "_meta.json"):
            result = get_qfq_kline("000001.SZ")
            assert not result.empty
            assert (self.qfq_dir / "000001.SZ.parquet").exists()

    @patch("services.qfq_cache.RAW_KLINE_DIR")
    @patch("services.qfq_cache.QFQ_KLINE_DIR")
    @patch("services.qfq_cache.DIVIDEND_DIR")
    def test_invalidate_cache_removes_file(self, mock_div, mock_qfq, mock_raw):
        mock_qfq.__truediv__ = lambda s, x: self.qfq_dir / x
        cache_file = self.qfq_dir / "000001.SZ.parquet"
        cache_file.write_text("dummy")
        meta_file = self.qfq_dir / "_meta.json"
        meta_file.write_text(json.dumps({"000001.SZ": {"last_ex_date": "2025-06-12", "raw_latest_date": "2025-06-13"}}))

        with patch("services.qfq_cache.QFQ_META_FILE", meta_file):
            invalidate_cache(["000001.SZ"])
            assert not cache_file.exists()
            meta = json.loads(meta_file.read_text())
            assert "000001.SZ" not in meta


class TestGetLatestExDate:
    def test_returns_latest_ex_date(self):
        div_df = pd.DataFrame({
            "报告期": ["2024-12-31", "2025-06-30"],
            "除权除息日": ["2025-06-12", "2025-10-15"],
            "方案进度": ["实施分配", "实施分配"],
        })
        with tempfile.TemporaryDirectory() as tmp:
            div_dir = Path(tmp)
            div_df.to_parquet(div_dir / "000001.SZ.parquet", index=False)
            with patch("services.qfq_cache.DIVIDEND_DIR", div_dir):
                result = get_latest_ex_date("000001.SZ")
                assert result == "2025-10-15"

    def test_returns_none_when_no_dividend(self):
        with tempfile.TemporaryDirectory() as tmp:
            div_dir = Path(tmp)
            with patch("services.qfq_cache.DIVIDEND_DIR", div_dir):
                result = get_latest_ex_date("999999.SZ")
                assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_qfq_cache.py::TestCacheManagement -x -v`
Expected: FAIL with "ImportError" (get_qfq_kline not defined)

- [ ] **Step 3: Implement cache management functions**

追加到 `backend/services/qfq_cache.py`：

```python
def get_latest_ex_date(symbol: str) -> str | None:
    div_path = DIVIDEND_DIR / f"{symbol}.parquet"
    if not div_path.exists():
        return None
    div_df = pd.read_parquet(div_path)
    impl = _get_implemented_dividends(div_df)
    if impl.empty:
        return None
    ex_dates = impl["除权除息日"].astype(str).sort_values()
    return ex_dates.iloc[-1]


def _is_cache_valid(symbol: str, meta: dict) -> tuple[str, bool]:
    entry = meta.get(symbol)
    if entry is None:
        return "miss", False

    current_ex_date = get_latest_ex_date(symbol) or ""
    cached_ex_date = entry.get("last_ex_date", "")
    if current_ex_date != cached_ex_date:
        return "ex_date_changed", False

    raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
    if not raw_path.exists():
        return "no_raw", False
    raw_df = pd.read_parquet(raw_path, columns=["date"])
    raw_latest = raw_df.iloc[0]["date"] if not raw_df.empty else ""
    cached_latest = entry.get("raw_latest_date", "")
    if raw_latest > cached_latest:
        return "raw_newer", False

    return "valid", True


def get_qfq_kline(symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    QFQ_KLINE_DIR.mkdir(parents=True, exist_ok=True)
    meta = _load_meta()
    cache_path = QFQ_KLINE_DIR / f"{symbol}.parquet"

    status, valid = _is_cache_valid(symbol, meta)

    if valid and cache_path.exists():
        df = pd.read_parquet(cache_path)
    elif status == "raw_newer" and cache_path.exists():
        cached_df = pd.read_parquet(cache_path)
        raw_df = pd.read_parquet(RAW_KLINE_DIR / f"{symbol}.parquet")
        cached_latest = meta[symbol]["raw_latest_date"]
        raw_asc = raw_df.sort_values("date")
        new_rows = raw_asc[raw_asc["date"] > cached_latest]
        if not new_rows.empty:
            df = pd.concat([new_rows.sort_values("date", ascending=False), cached_df], ignore_index=True)
        else:
            df = cached_df
        df.to_parquet(cache_path, index=False)
        raw_latest = raw_df.iloc[0]["date"] if not raw_df.empty else ""
        meta[symbol] = {
            "last_ex_date": get_latest_ex_date(symbol) or "",
            "raw_latest_date": raw_latest,
        }
        _save_meta(meta)
    else:
        raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
        if not raw_path.exists():
            return pd.DataFrame()
        raw_df = pd.read_parquet(raw_path)
        div_path = DIVIDEND_DIR / f"{symbol}.parquet"
        div_df = pd.read_parquet(div_path) if div_path.exists() else pd.DataFrame()
        df = compute_qfq(raw_df, div_df)
        df.to_parquet(cache_path, index=False)
        raw_latest = raw_df.iloc[0]["date"] if not raw_df.empty else ""
        meta[symbol] = {
            "last_ex_date": get_latest_ex_date(symbol) or "",
            "raw_latest_date": raw_latest,
        }
        _save_meta(meta)

    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    return df


def invalidate_cache(symbols: list[str]):
    meta = _load_meta()
    for symbol in symbols:
        cache_path = QFQ_KLINE_DIR / f"{symbol}.parquet"
        if cache_path.exists():
            cache_path.unlink()
        meta.pop(symbol, None)
    _save_meta(meta)


def invalidate_all():
    for f in QFQ_KLINE_DIR.glob("*.parquet"):
        f.unlink()
    _save_meta({})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_qfq_cache.py -x -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/qfq_cache.py backend/tests/test_qfq_cache.py
git commit -m "feat: 实现 qfq 缓存管理（get_qfq_kline / invalidate）"
```

---

### Task 4: 替换 routers/stock.py 中的 qfq 读取

**Files:**
- Modify: `backend/routers/stock.py`

- [ ] **Step 1: Modify stock router to use qfq_cache**

将 `routers/stock.py` 中 adjust=qfq 时直接读目录的逻辑改为调用 `get_qfq_kline`：

```python
from services.qfq_cache import get_qfq_kline
```

`api_get_kline` 函数修改：
```python
@router.get("/{symbol}/kline")
def api_get_kline(
    symbol: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    period: str = Query("daily", description="daily/weekly/monthly"),
    adjust: str = Query("raw", description="raw/qfq"),
):
    if adjust == "qfq":
        df = get_qfq_kline(symbol, start_date=start_date, end_date=end_date)
        if df.empty:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
    else:
        filepath = RAW_KLINE_DIR / f"{symbol}.parquet"
        if not filepath.exists():
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")
        df = get_kline(filepath, start_date=start_date, end_date=end_date)
    if period in ("weekly", "monthly"):
        df = aggregate_kline(df, period=period)
    return df.to_dict(orient="records")
```

`api_get_indicators` 函数同理修改。

- [ ] **Step 2: Run existing API tests**

Run: `python -m pytest backend/tests/test_api.py -x -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/routers/stock.py
git commit -m "refactor: stock router 使用 qfq_cache 替代直接读 qfq 目录"
```

---

### Task 5: 替换 routers/backtest.py 和 routers/screener.py 中的 qfq 读取

**Files:**
- Modify: `backend/routers/backtest.py`
- Modify: `backend/routers/screener.py`

- [ ] **Step 1: Modify backtest router**

修改 `_load_stock_data` 函数：

```python
from services.qfq_cache import get_qfq_kline
from config import QFQ_KLINE_DIR, RAW_KLINE_DIR

def _load_stock_data(start_date: str = None, end_date: str = None, symbols: list[str] = None) -> dict[str, pd.DataFrame]:
    stock_data = {}
    if symbols is not None:
        target_symbols = [s for s in symbols if (RAW_KLINE_DIR / f"{s}.parquet").exists()]
    else:
        target_symbols = [f.stem for f in RAW_KLINE_DIR.glob("*.parquet")]
    for symbol in target_symbols:
        df = get_qfq_kline(symbol, start_date=start_date, end_date=end_date)
        if not df.empty:
            stock_data[symbol] = df
    return stock_data
```

- [ ] **Step 2: Modify screener router**

修改 `api_run_screener` 中的数据加载：

```python
from services.qfq_cache import get_qfq_kline
from config import RAW_KLINE_DIR

    stock_data = {}
    for filepath in RAW_KLINE_DIR.glob("*.parquet"):
        symbol = filepath.stem
        df = get_qfq_kline(symbol)
        if not df.empty:
            stock_data[symbol] = df
```

- [ ] **Step 3: Run backtest and screener tests**

Run: `python -m pytest backend/tests/test_backtest_api.py backend/tests/test_screener_api.py -x -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/backtest.py backend/routers/screener.py
git commit -m "refactor: backtest/screener 使用 qfq_cache 替代直接读 qfq 目录"
```

---

### Task 6: 替换其他引用 QFQ_KLINE_DIR 的模块

**Files:**
- Modify: `backend/services/dividend_updater.py`
- Modify: `backend/services/valuation_updater.py`
- Modify: `backend/services/indicator_store.py`
- Modify: `backend/scheduler.py`

- [ ] **Step 1: Modify dividend_updater.py**

`get_all_symbols()` 改为从 RAW_KLINE_DIR 获取：

```python
from config import DIVIDEND_DIR, RAW_KLINE_DIR, LOG_DIR

def get_all_symbols() -> list[str]:
    return [f.stem for f in sorted(RAW_KLINE_DIR.glob("*.parquet"))]
```

- [ ] **Step 2: Modify valuation_updater.py**

同样修改 symbol 列表来源为 RAW_KLINE_DIR。

- [ ] **Step 3: Modify indicator_store.py**

`run_full_precompute` 改为从 qfq_cache 获取数据：

```python
from services.qfq_cache import get_qfq_kline
from config import INDICATOR_DIR, RAW_KLINE_DIR

def run_full_precompute(progress_callback=None):
    files = list(RAW_KLINE_DIR.glob("*.parquet"))
    total = len(files)
    for i, filepath in enumerate(files, 1):
        symbol = filepath.stem
        try:
            df = get_qfq_kline(symbol)
            if not df.empty:
                compute_and_save(symbol, df)
        except Exception as e:
            if progress_callback:
                progress_callback(f"指标预计算失败 {symbol}: {e}")
        if progress_callback and (i % 500 == 0 or i == total):
            progress_callback(f"指标预计算进度 {i}/{total}")
```

- [ ] **Step 4: Modify scheduler.py**

快照中获取 symbol 列表改为 RAW_KLINE_DIR。

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/dividend_updater.py backend/services/valuation_updater.py backend/services/indicator_store.py backend/scheduler.py
git commit -m "refactor: 所有模块从 RAW_KLINE_DIR 获取 symbol 列表"
```

---

### Task 7: dividend 更新后联动清理 qfq 缓存

**Files:**
- Modify: `backend/services/dividend_updater.py`
- Modify: `backend/tests/test_qfq_cache.py`

- [ ] **Step 1: Write failing test**

追加到 `backend/tests/test_qfq_cache.py`：

```python
class TestDividendInvalidation:
    def test_new_ex_date_invalidates_cache(self):
        import tempfile
        from pathlib import Path
        from services.qfq_cache import get_latest_ex_date, _load_meta, _save_meta

        with tempfile.TemporaryDirectory() as tmp:
            qfq_dir = Path(tmp) / "qfq"
            qfq_dir.mkdir()
            div_dir = Path(tmp) / "div"
            div_dir.mkdir()

            meta = {"000001.SZ": {"last_ex_date": "2025-06-12", "raw_latest_date": "2025-10-16"}}
            meta_file = qfq_dir / "_meta.json"
            meta_file.write_text(json.dumps(meta))

            new_div = pd.DataFrame({
                "报告期": ["2024-12-31", "2025-06-30"],
                "送转股份-送股比例": [0.0, 0.0],
                "送转股份-转股比例": [0.0, 0.0],
                "现金分红-现金分红比例": [5.0, 2.0],
                "除权除息日": ["2025-06-12", "2025-10-15"],
                "方案进度": ["实施分配", "实施分配"],
            })
            new_div.to_parquet(div_dir / "000001.SZ.parquet", index=False)

            with patch("services.qfq_cache.DIVIDEND_DIR", div_dir):
                ex_date = get_latest_ex_date("000001.SZ")
                assert ex_date == "2025-10-15"
                assert ex_date != meta["000001.SZ"]["last_ex_date"]
```

- [ ] **Step 2: Modify dividend_updater to invalidate cache after update**

在 `run_dividend_update` 函数末尾追加：

```python
from services.qfq_cache import invalidate_cache, get_latest_ex_date, _load_meta

    updated_symbols_with_new_ex = []
    meta = _load_meta()
    for sym in symbols:
        if sym in [s for s in symbols if (dividend_dir / f"{sym}.parquet").exists()]:
            current_ex = get_latest_ex_date(sym)
            cached_ex = meta.get(sym, {}).get("last_ex_date", "")
            if current_ex and current_ex != cached_ex:
                updated_symbols_with_new_ex.append(sym)

    if updated_symbols_with_new_ex:
        invalidate_cache(updated_symbols_with_new_ex)
        _log_progress(f"检测到 {len(updated_symbols_with_new_ex)} 只股票有新除权日, 已清理qfq缓存")
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest backend/tests/test_qfq_cache.py backend/tests/test_data_updater.py -x -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/dividend_updater.py backend/tests/test_qfq_cache.py
git commit -m "feat: dividend 更新后联动清理 qfq 缓存"
```

---

### Task 8: data_updater 更新 raw 后同步追加 qfq 缓存

**Files:**
- Modify: `backend/services/data_updater.py`

- [ ] **Step 1: Modify data_updater to append to qfq cache**

在 `run_incremental_update` 中，每只股票 raw 追加完成后，同时追加到 qfq 缓存：

```python
from services.qfq_cache import QFQ_META_FILE, _load_meta, _save_meta

# 在循环结束后，批量更新 qfq 缓存
if updated_symbols:
    _log_progress(f"同步更新 {len(updated_symbols)} 只股票的 qfq 缓存...")
    meta = _load_meta()
    for symbol in updated_symbols:
        qfq_path = QFQ_KLINE_DIR / f"{symbol}.parquet"
        if qfq_path.exists():
            existing = pd.read_parquet(qfq_path)
            latest_cached = existing.iloc[0]["date"] if not existing.empty else ""
            if today_str > latest_cached:
                raw_path = RAW_KLINE_DIR / f"{symbol}.parquet"
                raw_df = pd.read_parquet(raw_path)
                new_row = raw_df[raw_df["date"] == today_str]
                if not new_row.empty:
                    merged = pd.concat([new_row, existing], ignore_index=True)
                    merged.to_parquet(qfq_path, index=False)
        meta_entry = meta.get(symbol, {})
        meta_entry["raw_latest_date"] = today_str
        meta[symbol] = meta_entry
    _save_meta(meta)
    _log_progress("qfq 缓存同步完成")
```

- [ ] **Step 2: Run data updater tests**

Run: `python -m pytest backend/tests/test_data_updater.py -x -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/services/data_updater.py
git commit -m "feat: data_updater 更新 raw 后同步追加 qfq 缓存"
```

---

### Task 9: 清理无用的 QFQ_KLINE_DIR 直接引用 & 全量测试

**Files:**
- Modify: `backend/config.py` (add comment about qfq being cache)
- Modify: `backend/tests/test_strategy_regression.py`

- [ ] **Step 1: Update test_strategy_regression to use qfq_cache**

```python
from services.qfq_cache import get_qfq_kline
from config import RAW_KLINE_DIR

DATA_AVAILABLE = RAW_KLINE_DIR.exists() and any(RAW_KLINE_DIR.glob("*.parquet"))
skip_no_data = pytest.mark.skipif(not DATA_AVAILABLE, reason="raw parquet data not available")

# 将所有 pd.read_parquet(QFQ_KLINE_DIR / ...) 改为 get_qfq_kline(symbol)
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_strategy_regression.py backend/config.py
git commit -m "refactor: 清理残留 QFQ_KLINE_DIR 直接引用"
```

---

### Task 10: 运行验证测试确认最终正确性

- [ ] **Step 1: 生成全部 qfq 缓存**

```bash
cd backend && python -c "
from services.qfq_cache import get_qfq_kline
from config import RAW_KLINE_DIR
files = list(RAW_KLINE_DIR.glob('*.parquet'))
for i, f in enumerate(files, 1):
    get_qfq_kline(f.stem)
    if i % 500 == 0:
        print(f'{i}/{len(files)}')
print('Done')
"
```

- [ ] **Step 2: Run validation test**

Run: `python -m pytest backend/tests/test_qfq_validation.py -x -v -s`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 4: Final commit**

```bash
git commit --allow-empty -m "验证通过: qfq 缓存重构完成，30只股票对比验证一致"
```
