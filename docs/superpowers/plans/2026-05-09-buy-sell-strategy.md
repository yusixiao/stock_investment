# 买入/卖出策略体系 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TraderStrategy with independent BuyStrategy + SellStrategy, support signal-table mode for chained execution from screener results.

**Architecture:** BuyStrategy and SellStrategy are new base classes sharing a Broker. Engine detects buy/sell nodes in pipeline and merges them into a single backtest loop. Signal-table mode skips screener execution when source_run_id provides match_dates.

**Tech Stack:** Python (FastAPI backend), Vue 3 frontend, SQLite persistence

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/services/backtest/base.py` | Add BuyStrategy, SellStrategy; keep TraderStrategy temporarily for backward compat |
| `backend/services/backtest/buy_sell_engine.py` | New file: BuySellEngine — handles buy/sell backtest loop with signal-table support |
| `backend/services/backtest/context.py` | Add BuyContext, SellContext (extend TraderContext with minor diffs) |
| `backend/services/backtest/group_manager.py` | Modify `_execute_step` to detect buy/sell and delegate to BuySellEngine |
| `backend/services/backtest/strategy_loader.py` | Recognize BuyStrategy/SellStrategy in scanning |
| `backend/routers/strategy_group.py` | Pass `initial_capital` from run request body |
| `frontend/src/components/PipelineBuilder.vue` | Show buy/sell badges with colors |
| `frontend/src/views/StrategyGroupDetail.vue` | Add initial_capital field to run dialog |
| `strategies/examples/equal_weight_buyer.py` | Example BuyStrategy (rewrite from equal_weight_trader) |
| `strategies/examples/pe_sell.py` | Example SellStrategy (PE > threshold triggers sell) |
| `backend/tests/test_buy_sell_engine.py` | Tests for BuySellEngine |
| `backend/tests/test_buy_sell_signal_table.py` | Tests for signal-table mode |

---

### Task 1: Add BuyStrategy and SellStrategy base classes

**Files:**
- Modify: `backend/services/backtest/base.py`
- Test: `backend/tests/test_buy_sell_base.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.backtest.base import BuyStrategy, SellStrategy


def test_buy_strategy_type():
    class MyBuyer(BuyStrategy):
        name = "test"
        def on_bar(self, ctx):
            pass
    b = MyBuyer()
    assert b.strategy_type == "buy"


def test_sell_strategy_type():
    class MySeller(SellStrategy):
        name = "test"
        def on_bar(self, ctx):
            pass
    s = MySeller()
    assert s.strategy_type == "sell"


def test_buy_strategy_params():
    class MyBuyer(BuyStrategy):
        name = "test"
        params = {"weight": {"default": 0.5}}
        def on_bar(self, ctx):
            pass
    b = MyBuyer(param_overrides={"weight": 0.8})
    assert b.p.weight == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_buy_sell_base.py -v`
Expected: FAIL with ImportError (BuyStrategy not defined)

- [ ] **Step 3: Write minimal implementation**

In `backend/services/backtest/base.py`, add after `TraderStrategy` class:

```python
class BuyStrategy(BaseStrategy):
    strategy_type = "buy"

    def on_bar(self, ctx):
        raise NotImplementedError


class SellStrategy(BaseStrategy):
    strategy_type = "sell"

    def on_bar(self, ctx):
        raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_buy_sell_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/base.py backend/tests/test_buy_sell_base.py
git commit -m "feat: add BuyStrategy and SellStrategy base classes"
```

---

### Task 2: Create BuySellEngine with full-mode execution

**Files:**
- Create: `backend/services/backtest/buy_sell_engine.py`
- Test: `backend/tests/test_buy_sell_engine.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from services.backtest.base import ScreenerStrategy, BuyStrategy, SellStrategy
from services.backtest.buy_sell_engine import BuySellEngine


class SimpleScreener(ScreenerStrategy):
    name = "simple"
    def screen(self, ctx, symbols):
        return symbols[:2]


class SimpleBuyer(BuyStrategy):
    name = "buy_all"
    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if ctx.get_position(sym) is None:
                ctx.order_value(sym, ctx.available_cash / max(len(ctx.selected_symbols), 1))


class SimpleSeller(SellStrategy):
    name = "sell_drop"
    params = {"drop_pct": {"default": 0.05}}
    def on_bar(self, ctx):
        for sym in list(ctx.get_positions()):
            pos = ctx.get_position(sym)
            price = ctx.get_price(sym)
            if pos and price:
                if price["close"] < pos["avg_cost"] * (1 - self.p.drop_pct):
                    ctx.order_shares(sym, -pos["shares"])


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002", "000003"]:
        base = 10.0 if sym == "000001" else 20.0 if sym == "000002" else 30.0
        rows = []
        for i, d in enumerate(dates):
            p = base + i * 0.1
            rows.append({"date": d, "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000000, "amount": p * 1000000})
        data[sym] = pd.DataFrame(rows)
    return data


def test_buy_sell_engine_basic():
    stock_data = _make_stock_data()
    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[SimpleScreener()],
        buyer=SimpleBuyer(),
        seller=SimpleSeller(),
        initial_capital=1_000_000,
    )
    result = engine.run()
    assert "metrics" in result
    assert "equity_curve" in result
    assert "trades" in result
    assert result["metrics"]["total_return"] != 0 or len(result["trades"]) > 0


def test_buy_sell_engine_no_screener():
    stock_data = _make_stock_data()
    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[],
        buyer=SimpleBuyer(),
        seller=SimpleSeller(),
        initial_capital=1_000_000,
    )
    result = engine.run()
    assert "metrics" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_buy_sell_engine.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write BuySellEngine implementation**

Create `backend/services/backtest/buy_sell_engine.py`:

```python
import pandas as pd
from typing import Callable

from services.backtest.base import ScreenerStrategy, BuyStrategy, SellStrategy
from services.backtest.broker import Broker
from services.backtest.context import TraderContext
from services.backtest.analyzer import compute_metrics
from services.stock_data import aggregate_kline


class BuySellEngine:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy] | None = None,
        buyer: BuyStrategy | None = None,
        seller: SellStrategy | None = None,
        initial_capital: float = 1_000_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.002,
        on_progress: Callable[[int, int, str], None] | None = None,
        signal_table: dict[str, list[str]] | None = None,
        valuation_data: dict[str, pd.DataFrame] | None = None,
        dividend_data: dict[str, pd.DataFrame] | None = None,
        financial_data: dict[str, pd.DataFrame] | None = None,
        join_modes: list[str] | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners or []
        self._buyer = buyer
        self._seller = seller
        self._initial_capital = initial_capital
        self._commission_rate = commission_rate
        self._slippage = slippage
        self._on_progress = on_progress
        self._signal_table = signal_table
        self._valuation_data = valuation_data or {}
        self._dividend_data = dividend_data or {}
        self._financial_data = financial_data or {}
        self._all_symbols = list(self._stock_data.keys())

        n = max(0, len(self._screeners) - 1)
        self._join_modes = (join_modes or [])[:n]
        while len(self._join_modes) < n:
            self._join_modes.append("independent")

        self._weekly_data: dict[str, pd.DataFrame] = {}
        self._monthly_data: dict[str, pd.DataFrame] = {}
        self._precompute_periods()

    def _report(self, current: int, total: int, phase: str):
        if self._on_progress:
            self._on_progress(current, total, phase)

    def _precompute_periods(self):
        needs_weekly = any(getattr(s, "frequency", "daily") == "weekly" for s in self._screeners)
        needs_monthly = any(getattr(s, "frequency", "daily") == "monthly" for s in self._screeners)
        if not needs_weekly and not needs_monthly:
            return
        total = len(self._stock_data)
        count = 0
        for sym, df in self._stock_data.items():
            if needs_weekly:
                self._weekly_data[sym] = aggregate_kline(df, period="weekly")
            if needs_monthly:
                self._monthly_data[sym] = aggregate_kline(df, period="monthly")
            count += 1
            if count % 500 == 0 or count == total:
                self._report(count, total, "预计算周期数据")

    def _period_key(self, date_str: str, freq: str) -> str:
        if freq == "monthly":
            return date_str[:7]
        if freq == "weekly":
            from datetime import date as _date
            dt = _date.fromisoformat(date_str)
            yr, wk, _ = dt.isocalendar()
            return f"{yr}-W{wk:02d}"
        return date_str

    def _get_signal_symbols(self, current_date: str) -> list[str]:
        if self._signal_table is None:
            return []
        return self._signal_table.get(current_date, [])

    def run(self) -> dict:
        broker = Broker(
            initial_capital=self._initial_capital,
            commission_rate=self._commission_rate,
            slippage=self._slippage,
        )

        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)

        equity_curve = []
        prev_closes: dict[str, float] = {}
        screener_cache: dict[int, list[str]] = {}
        prev_keys: dict[int, str] = {}

        use_signal_table = self._signal_table is not None

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "回测中")

            current_date = ref_df.iloc[idx]["date"]
            current_bars = {}
            current_prices = {}
            for sym, df in self._stock_data.items():
                if idx < len(df):
                    row = df.iloc[idx]
                    current_bars[sym] = {
                        "open": row["open"],
                        "close": row["close"],
                        "high": row["high"],
                        "low": row["low"],
                    }
                    current_prices[sym] = row["close"]

            if idx > 0:
                broker.fill_orders(current_date, current_bars, prev_closes)

            if use_signal_table:
                selected_symbols = self._get_signal_symbols(current_date)
            else:
                selected_symbols = self._run_screeners(idx, current_date, current_bars, screener_cache, prev_keys)

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=selected_symbols,
                days_since_rebalance=0,
                weekly_data=self._weekly_data,
                monthly_data=self._monthly_data,
                valuation_data=self._valuation_data,
                dividend_data=self._dividend_data,
                financial_data=self._financial_data,
            )

            if self._buyer and selected_symbols:
                try:
                    self._buyer.on_bar(trader_ctx)
                except Exception:
                    pass

            if self._seller:
                try:
                    self._seller.on_bar(trader_ctx)
                except Exception:
                    pass

            snap = broker.portfolio.snapshot(current_date, current_prices)
            equity_curve.append(snap)
            prev_closes = dict(current_prices)

        metrics = compute_metrics(equity_curve, broker.all_trades, self._initial_capital)
        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": broker.all_trades,
        }

    def _run_screeners(self, idx: int, current_date: str, current_bars: dict, cache: dict, prev_keys: dict) -> list[str]:
        if not self._screeners:
            return list(current_bars.keys())

        from services.backtest.context import ScreenerContext

        screener_sets: list[set[str]] = []
        available = list(current_bars.keys())

        for si, screener in enumerate(self._screeners):
            freq = getattr(screener, "frequency", "daily")
            pk = self._period_key(current_date, freq)
            need_run = (si not in prev_keys) or (pk != prev_keys[si])
            if need_run:
                ctx = ScreenerContext(
                    stock_data=self._stock_data,
                    current_idx=idx,
                    frequency=freq,
                    weekly_data=self._weekly_data,
                    monthly_data=self._monthly_data,
                    valuation_data=self._valuation_data,
                    dividend_data=self._dividend_data,
                    financial_data=self._financial_data,
                )
                raw = screener.screen(ctx, list(available))
                symbols = []
                for item in raw:
                    if isinstance(item, dict):
                        symbols.append(item["symbol"])
                    else:
                        symbols.append(item)
                cache[si] = symbols
                prev_keys[si] = pk
            screener_sets.append(set(cache.get(si, [])))

        merged = screener_sets[0] if screener_sets else set(available)
        for i, jm in enumerate(self._join_modes):
            next_set = screener_sets[i + 1]
            if jm == "correlated":
                merged = merged & next_set
            else:
                merged = merged | next_set

        return [s for s in available if s in merged]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_buy_sell_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/buy_sell_engine.py backend/tests/test_buy_sell_engine.py
git commit -m "feat: add BuySellEngine for buy/sell strategy execution"
```

---

### Task 3: Signal-table mode in BuySellEngine

**Files:**
- Modify: `backend/services/backtest/buy_sell_engine.py` (already supports it)
- Test: `backend/tests/test_buy_sell_signal_table.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from services.backtest.base import BuyStrategy, SellStrategy
from services.backtest.buy_sell_engine import BuySellEngine


class AlwaysBuyer(BuyStrategy):
    name = "always_buy"
    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if ctx.get_position(sym) is None:
                ctx.order_value(sym, ctx.available_cash / max(len(ctx.selected_symbols), 1))


class NeverSeller(SellStrategy):
    name = "never_sell"
    def on_bar(self, ctx):
        pass


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        for i, d in enumerate(dates):
            p = base + i * 0.1
            rows.append({"date": d, "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000000, "amount": p * 1000000})
        data[sym] = pd.DataFrame(rows)
    return data


def test_signal_table_only_buys_on_signal_dates():
    stock_data = _make_stock_data()
    signal_table = {
        "2024-01-05": ["000001"],
        "2024-01-10": ["000002"],
    }
    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[],
        buyer=AlwaysBuyer(),
        seller=NeverSeller(),
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    result = engine.run()
    buy_trades = [t for t in result["trades"] if t["direction"] == "buy"]
    buy_dates = [t["date"] for t in buy_trades]
    assert "2024-01-06" in buy_dates or "2024-01-07" in buy_dates
    assert "2024-01-11" in buy_dates or "2024-01-13" in buy_dates
    assert "2024-01-03" not in buy_dates


def test_signal_table_seller_runs_every_bar():
    stock_data = _make_stock_data()
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]

    class SellOnDay10(SellStrategy):
        name = "sell_day10"
        def on_bar(self, ctx):
            if ctx.current_date == "2024-01-14":
                for sym in list(ctx.get_positions()):
                    pos = ctx.get_position(sym)
                    if pos:
                        ctx.order_shares(sym, -pos["shares"])

    signal_table = {"2024-01-05": ["000001"]}
    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[],
        buyer=AlwaysBuyer(),
        seller=SellOnDay10(),
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    result = engine.run()
    sell_trades = [t for t in result["trades"] if t["direction"] == "sell"]
    assert len(sell_trades) > 0
    assert sell_trades[0]["date"] == "2024-01-15"


def test_signal_table_empty_means_no_buy():
    stock_data = _make_stock_data()
    signal_table = {}
    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[],
        buyer=AlwaysBuyer(),
        seller=NeverSeller(),
        initial_capital=1_000_000,
        signal_table=signal_table,
    )
    result = engine.run()
    assert len(result["trades"]) == 0
```

- [ ] **Step 2: Run test to verify it passes (signal_table already implemented in Task 2)**

Run: `python -m pytest backend/tests/test_buy_sell_signal_table.py -v`
Expected: PASS (if not, debug and fix)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_buy_sell_signal_table.py
git commit -m "test: add signal-table mode tests for BuySellEngine"
```

---

### Task 4: Update strategy_loader to recognize buy/sell types

**Files:**
- Modify: `backend/services/backtest/strategy_loader.py`
- Test: `backend/tests/test_strategy_loader_buy_sell.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
from services.backtest.strategy_loader import load_strategy_from_file, scan_strategies


def test_load_buy_strategy():
    code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import BuyStrategy

class MyBuyer(BuyStrategy):
    name = "test buyer"
    strategy_type = "buy"
    def on_bar(self, ctx):
        pass
'''
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        classes = load_strategy_from_file(Path(f.name))
    assert len(classes) == 1
    assert classes[0].strategy_type == "buy"


def test_scan_returns_buy_sell_types():
    code_buy = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import BuyStrategy

class TestBuyer(BuyStrategy):
    name = "test buyer"
    def on_bar(self, ctx):
        pass
'''
    code_sell = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import SellStrategy

class TestSeller(SellStrategy):
    name = "test seller"
    def on_bar(self, ctx):
        pass
'''
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "buyer.py").write_text(code_buy)
        (Path(d) / "seller.py").write_text(code_sell)
        results = scan_strategies(Path(d))
    types = [r["strategy_type"] for r in results]
    assert "buy" in types
    assert "sell" in types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_strategy_loader_buy_sell.py -v`
Expected: FAIL (BuyStrategy/SellStrategy not excluded from base check)

- [ ] **Step 3: Update strategy_loader.py**

Modify `backend/services/backtest/strategy_loader.py`:

```python
import importlib.util
import inspect
from pathlib import Path

from services.backtest.base import BaseStrategy, ScreenerStrategy, TraderStrategy, BuyStrategy, SellStrategy


def load_strategy_from_file(filepath: Path) -> list[type]:
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Strategy file not found: {filepath}")

    spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    strategies = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, BaseStrategy)
            and obj not in (BaseStrategy, ScreenerStrategy, TraderStrategy, BuyStrategy, SellStrategy)
            and obj.__module__ == module.__name__
        ):
            strategies.append(obj)
    return strategies


def scan_strategies(directory: Path) -> list[dict]:
    directory = Path(directory)
    results = []
    for filepath in sorted(directory.rglob("*.py")):
        if filepath.name.startswith("_"):
            continue
        try:
            classes = load_strategy_from_file(filepath)
        except Exception:
            continue
        for cls in classes:
            info = {
                "name": cls.name,
                "description": cls.description,
                "strategy_type": cls.strategy_type,
                "params": cls.params,
                "filepath": str(filepath),
                "class_name": cls.__name__,
            }
            if hasattr(cls, "frequency"):
                info["frequency"] = cls.frequency
            results.append(info)
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_strategy_loader_buy_sell.py -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to ensure no regression**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/strategy_loader.py backend/tests/test_strategy_loader_buy_sell.py
git commit -m "feat: strategy_loader recognizes BuyStrategy and SellStrategy"
```

---

### Task 5: Integrate BuySellEngine into GroupRunner

**Files:**
- Modify: `backend/services/backtest/group_manager.py`
- Test: `backend/tests/test_group_runner_buy_sell.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import json
import pandas as pd
from unittest.mock import patch, MagicMock
from services.backtest.group_manager import GroupManager, GroupRunner, _execute_step
from services.backtest.task_manager import TaskManager


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        for i, d in enumerate(dates):
            p = base + i * 0.1
            rows.append({"date": d, "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000000, "amount": p * 1000000})
        data[sym] = pd.DataFrame(rows)
    return data


def _write_strategy_files(tmp_dir):
    screener_code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import ScreenerStrategy

class TestScreener(ScreenerStrategy):
    name = "test screener"
    def screen(self, ctx, symbols):
        return symbols[:2]
'''
    buyer_code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import BuyStrategy

class TestBuyer(BuyStrategy):
    name = "test buyer"
    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if ctx.get_position(sym) is None:
                ctx.order_value(sym, 100000)
'''
    seller_code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import SellStrategy

class TestSeller(SellStrategy):
    name = "test seller"
    def on_bar(self, ctx):
        pass
'''
    (Path(tmp_dir) / "screener.py").write_text(screener_code)
    (Path(tmp_dir) / "buyer.py").write_text(buyer_code)
    (Path(tmp_dir) / "seller.py").write_text(seller_code)
    return tmp_dir


def test_group_runner_detects_buy_sell_pipeline():
    with tempfile.TemporaryDirectory() as tmp_dir:
        _write_strategy_files(tmp_dir)
        db_path = str(Path(tmp_dir) / "test.db")
        gm = GroupManager(db_path=db_path)
        tm = TaskManager(db_path=db_path)
        runner = GroupRunner(group_manager=gm, task_manager=tm)

        pipeline = [
            {"filepath": str(Path(tmp_dir) / "screener.py"), "class_name": "TestScreener", "params": {}},
            {"filepath": str(Path(tmp_dir) / "buyer.py"), "class_name": "TestBuyer", "params": {}},
            {"filepath": str(Path(tmp_dir) / "seller.py"), "class_name": "TestSeller", "params": {}},
        ]
        group_id = gm.create_group("test", pipeline, ["correlated", "correlated"])

        stock_data = _make_stock_data()
        with patch("services.backtest.group_manager.get_qfq_kline") as mock_kline, \
             patch("services.backtest.group_manager.RAW_KLINE_DIR") as mock_dir:
            mock_dir.glob.return_value = [Path(f"{s}.parquet") for s in stock_data.keys()]
            mock_kline.side_effect = lambda sym, **kw: stock_data.get(sym, pd.DataFrame())

            run_id = runner.run_auto(group_id, "2024-01-02", "2024-01-22")

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        assert run["final_result"] is not None
        assert "metrics" in run["final_result"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_group_runner_buy_sell.py::test_group_runner_detects_buy_sell_pipeline -v`
Expected: FAIL (GroupRunner doesn't handle buy/sell yet)

- [ ] **Step 3: Modify GroupRunner to handle buy/sell pipeline**

In `backend/services/backtest/group_manager.py`, modify `_execute_step` and add a helper `_execute_buy_sell_pipeline`:

Add import at top of the runtime section (after line 377):
```python
from services.backtest.base import ScreenerStrategy, TraderStrategy, BuyStrategy, SellStrategy
```

Add new function `_execute_buy_sell_steps` after `_execute_step`:

```python
def _execute_buy_sell_steps(
    screener_configs: list[dict],
    buyer_config: dict | None,
    seller_config: dict | None,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    initial_capital: float,
    task_manager: TaskManager,
    signal_table: dict[str, list[str]] | None = None,
    join_modes: list[str] | None = None,
) -> tuple[str, dict]:
    from services.backtest.buy_sell_engine import BuySellEngine
    from services.qfq_cache import get_qfq_kline
    from config import RAW_KLINE_DIR, VALUATION_DIR, DIVIDEND_DIR, FINANCIAL_DIR
    import pandas as pd

    screeners = []
    for sc in screener_configs:
        filepath = Path(sc["filepath"])
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == sc["class_name"]), None)
        if cls:
            screeners.append(cls(param_overrides=sc.get("params", {})))

    buyer = None
    if buyer_config:
        filepath = Path(buyer_config["filepath"])
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == buyer_config["class_name"]), None)
        if cls:
            buyer = cls(param_overrides=buyer_config.get("params", {}))

    seller = None
    if seller_config:
        filepath = Path(seller_config["filepath"])
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == seller_config["class_name"]), None)
        if cls:
            seller = cls(param_overrides=seller_config.get("params", {}))

    task_id = task_manager.create_task(task_type="backtest", start_date=start_date, end_date=end_date)

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

    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=screeners if not signal_table else [],
        buyer=buyer,
        seller=seller,
        initial_capital=initial_capital,
        signal_table=signal_table,
        valuation_data=valuation_data,
        dividend_data=dividend_data,
        financial_data=financial_data,
        join_modes=join_modes,
    )
    result = engine.run()
    task_manager.complete_task(task_id, result)
    return task_id, result
```

Modify `GroupRunner.run_auto` and `_run_auto_with_run_id` to detect buy/sell in pipeline:

Add method to GroupRunner:

```python
def _has_buy_sell(self, pipeline: list[dict]) -> bool:
    for step in pipeline:
        filepath = Path(step["filepath"])
        try:
            classes = load_strategy_from_file(filepath)
            cls = next((c for c in classes if c.__name__ == step["class_name"]), None)
            if cls and (issubclass(cls, BuyStrategy) or issubclass(cls, SellStrategy)):
                return True
        except Exception:
            pass
    return False

def _split_pipeline(self, pipeline: list[dict]) -> tuple[list[dict], dict | None, dict | None]:
    screeners = []
    buyer = None
    seller = None
    for step in pipeline:
        filepath = Path(step["filepath"])
        try:
            classes = load_strategy_from_file(filepath)
            cls = next((c for c in classes if c.__name__ == step["class_name"]), None)
            if cls and issubclass(cls, BuyStrategy):
                buyer = step
            elif cls and issubclass(cls, SellStrategy):
                seller = step
            else:
                screeners.append(step)
        except Exception:
            screeners.append(step)
    return screeners, buyer, seller
```

In `_run_auto_with_run_id`, before the existing try block, add detection:

```python
if self._has_buy_sell(pipeline):
    screener_configs, buyer_config, seller_config = self._split_pipeline(pipeline)

    signal_table = None
    if source_run_id:
        source_run = gm.get_run(source_run_id)
        if source_run and source_run["final_result"]:
            signal_table = self._build_signal_table(source_run["final_result"], source_run_id)

    screener_join_modes = join_modes[:max(0, len(screener_configs) - 1)]

    try:
        task_id, result = _execute_buy_sell_steps(
            screener_configs=screener_configs,
            buyer_config=buyer_config,
            seller_config=seller_config,
            start_date=start_date,
            end_date=end_date,
            symbols=initial_symbols,
            initial_capital=initial_capital,
            task_manager=self._task_manager,
            signal_table=signal_table,
            join_modes=screener_join_modes,
        )
        steps_result = [{"step": 1, "input_count": len(initial_symbols) if initial_symbols else 0, "output_count": 0, "task_id": task_id}]
        gm.update_run_step(run_id, 1, steps_result)
        summary = self._build_summary(result)
        gm.update_run_status(run_id, "success", final_result=result, summary=summary)
    except Exception as e:
        gm.update_run_status(run_id, "failed", error=str(e))
    return
```

Add helper method:

```python
def _build_signal_table(self, final_result: dict, source_run_id: str) -> dict[str, list[str]]:
    gm = self._group_manager
    screened = final_result.get("screened_symbols", [])
    exclusions = {e["symbol"] for e in gm.list_exclusions(source_run_id)}

    table = {}
    for item in screened:
        if isinstance(item, dict):
            sym = item["symbol"]
            if sym in exclusions:
                continue
            for md in item.get("match_dates", []):
                if len(md) == 10:
                    table.setdefault(md, []).append(sym)
                else:
                    pass
        else:
            pass
    return table
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_group_runner_buy_sell.py -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/group_manager.py backend/tests/test_group_runner_buy_sell.py
git commit -m "feat: GroupRunner detects buy/sell pipeline and uses BuySellEngine"
```

---

### Task 6: Add initial_capital to group_runs table and API

**Files:**
- Modify: `backend/services/backtest/group_manager.py`
- Modify: `backend/routers/strategy_group.py`
- Test: `backend/tests/test_group_initial_capital.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
from services.backtest.group_manager import GroupManager


def test_create_run_with_initial_capital():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        gm = GroupManager(db_path=db_path)
        group_id = gm.create_group("test", [{"filepath": "x", "class_name": "Y"}])
        run_id = gm.create_run(group_id, "2024-01-01", "2024-12-31", "auto", initial_capital=500000)
        run = gm.get_run(run_id)
        assert run["initial_capital"] == 500000


def test_create_run_default_capital():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        gm = GroupManager(db_path=db_path)
        group_id = gm.create_group("test", [{"filepath": "x", "class_name": "Y"}])
        run_id = gm.create_run(group_id, "2024-01-01", "2024-12-31", "auto")
        run = gm.get_run(run_id)
        assert run["initial_capital"] == 1000000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_group_initial_capital.py -v`
Expected: FAIL

- [ ] **Step 3: Add initial_capital column and update create_run/get_run**

In `GroupManager._init_tables`, add migration:
```python
try:
    conn.execute("ALTER TABLE group_runs ADD COLUMN initial_capital REAL NOT NULL DEFAULT 1000000")
except sqlite3.OperationalError:
    pass
```

Update `create_run` signature and INSERT:
```python
def create_run(self, group_id: str, start_date: str | None, end_date: str | None, execution_mode: str, initial_capital: float = 1_000_000) -> str:
    run_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    conn = self._get_conn()
    try:
        conn.execute(
            "INSERT INTO group_runs (run_id, group_id, start_date, end_date, execution_mode, status, current_step, steps_result, initial_capital, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, group_id, start_date, end_date, execution_mode, "running", 0, "[]", initial_capital, now),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id
```

Update `get_run` to include `initial_capital`:
```python
"initial_capital": row["initial_capital"],
```

Update `backend/routers/strategy_group.py` `api_run_group`:
```python
initial_capital = body.get("initial_capital", 1_000_000)
```
Pass it to `create_run` and `_run_auto_with_run_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_group_initial_capital.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/group_manager.py backend/routers/strategy_group.py backend/tests/test_group_initial_capital.py
git commit -m "feat: add initial_capital to group_runs table and API"
```

---

### Task 7: Example strategies — equal_weight_buyer.py and pe_sell.py

**Files:**
- Create: `strategies/examples/equal_weight_buyer.py`
- Create: `strategies/examples/pe_sell.py`
- Test: `backend/tests/test_example_buy_sell_strategies.py`

- [ ] **Step 1: Write the example BuyStrategy**

Create `strategies/examples/equal_weight_buyer.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import BuyStrategy


class EqualWeightBuyer(BuyStrategy):
    name = "等权买入"
    description = "对选中股票等权分配资金买入"

    params = {
        "max_positions": {"default": 10},
    }

    def on_bar(self, ctx):
        targets = ctx.selected_symbols[:self.p.max_positions]
        if not targets:
            return
        portfolio = ctx.get_portfolio()
        per_stock = portfolio["total_value"] / self.p.max_positions
        for sym in targets:
            if ctx.get_position(sym) is None:
                ctx.order_value(sym, per_stock)
```

- [ ] **Step 2: Write the example SellStrategy**

Create `strategies/examples/pe_sell.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import SellStrategy


class PESell(SellStrategy):
    name = "PE卖出"
    description = "当持仓股票PE超过阈值时清仓卖出"

    params = {
        "pe_threshold": {"default": 40.0},
    }

    def on_bar(self, ctx):
        for sym in list(ctx.get_positions()):
            val = ctx.get_valuation(sym)
            if val is None:
                continue
            pe = val.get("pe")
            if pe is not None and pe > self.p.pe_threshold:
                pos = ctx.get_position(sym)
                if pos:
                    ctx.order_shares(sym, -pos["shares"])
```

- [ ] **Step 3: Write test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from services.backtest.buy_sell_engine import BuySellEngine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"))
from equal_weight_buyer import EqualWeightBuyer
from pe_sell import PESell


def _make_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    stock_data = {}
    valuation_data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        val_rows = []
        for i, d in enumerate(dates):
            p = base + i * 0.1
            rows.append({"date": d, "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000000, "amount": p * 1000000})
            val_rows.append({"date": d, "pe": 30.0 + i * 1.0, "pb": 2.0})
        stock_data[sym] = pd.DataFrame(rows)
        valuation_data[sym] = pd.DataFrame(val_rows)
    return stock_data, valuation_data


def test_equal_weight_buyer_and_pe_sell():
    stock_data, valuation_data = _make_data()
    signal_table = {"2024-01-03": ["000001", "000002"]}
    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=[],
        buyer=EqualWeightBuyer(),
        seller=PESell(param_overrides={"pe_threshold": 38.0}),
        initial_capital=1_000_000,
        signal_table=signal_table,
        valuation_data=valuation_data,
    )
    result = engine.run()
    assert len(result["trades"]) > 0
    buy_trades = [t for t in result["trades"] if t["direction"] == "buy"]
    sell_trades = [t for t in result["trades"] if t["direction"] == "sell"]
    assert len(buy_trades) > 0
    assert len(sell_trades) > 0
```

- [ ] **Step 4: Run test**

Run: `python -m pytest backend/tests/test_example_buy_sell_strategies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add strategies/examples/equal_weight_buyer.py strategies/examples/pe_sell.py backend/tests/test_example_buy_sell_strategies.py
git commit -m "feat: add example EqualWeightBuyer and PESell strategies"
```

---

### Task 8: Add TraderContext.available_cash property

**Files:**
- Modify: `backend/services/backtest/context.py`
- Test: `backend/tests/test_trader_context_cash.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from services.backtest.context import TraderContext
from services.backtest.portfolio import Portfolio


def test_available_cash():
    stock_data = {"000001": pd.DataFrame([{"date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000, "amount": 10000}])}
    portfolio = Portfolio(1_000_000)
    ctx = TraderContext(
        stock_data=stock_data,
        current_idx=0,
        portfolio=portfolio,
        broker_submit=lambda *a: None,
        selected_symbols=["000001"],
    )
    assert ctx.available_cash == 1_000_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_trader_context_cash.py -v`
Expected: FAIL (AttributeError: available_cash)

- [ ] **Step 3: Add available_cash property to TraderContext**

In `backend/services/backtest/context.py`, add to `TraderContext`:

```python
@property
def available_cash(self) -> float:
    return self._portfolio.cash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_trader_context_cash.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/context.py backend/tests/test_trader_context_cash.py
git commit -m "feat: add available_cash property to TraderContext"
```

---

### Task 9: Frontend — PipelineBuilder buy/sell badges + run dialog initial_capital

**Files:**
- Modify: `frontend/src/components/PipelineBuilder.vue`
- Modify: `frontend/src/views/StrategyGroupDetail.vue`
- Modify: `frontend/src/api/index.js`

- [ ] **Step 1: Update PipelineBuilder to show buy/sell badges**

In `frontend/src/components/PipelineBuilder.vue`, update the badge display:

Change line 6 from:
```html
<span :class="'badge ' + s.strategy_type">{{ s.strategy_type === 'screener' ? '筛选' : '交易' }}</span>
```
To:
```html
<span :class="'badge ' + s.strategy_type">{{ typeLabel(s.strategy_type) }}</span>
```

Change line 16 from:
```html
<span :class="'badge ' + item.strategy_type">{{ item.strategy_type === 'screener' ? '筛选' : '交易' }}</span>
```
To:
```html
<span :class="'badge ' + item.strategy_type">{{ typeLabel(item.strategy_type) }}</span>
```

Add function in `<script setup>`:
```javascript
function typeLabel(t) {
  const map = { screener: '筛选', trader: '交易', buy: '买入', sell: '卖出' }
  return map[t] || t
}
```

Update `addToPipeline` to handle buy/sell:
```javascript
function addToPipeline(strategy) {
  const hasBuy = props.pipeline.some(s => s.strategy_type === 'buy')
  const hasSell = props.pipeline.some(s => s.strategy_type === 'sell')
  const hasTrader = props.pipeline.some(s => s.strategy_type === 'trader')
  if (strategy.strategy_type === 'trader' && hasTrader) return
  if (strategy.strategy_type === 'buy' && hasBuy) return
  if (strategy.strategy_type === 'sell' && hasSell) return
  emit('update:pipeline', [...props.pipeline, { ...strategy }])
}
```

Add CSS for buy/sell badges:
```css
.badge.buy { background: #10b981; color: white; }
.badge.sell { background: #ef4444; color: white; }
```

- [ ] **Step 2: Update StrategyGroupDetail run dialog**

In `frontend/src/views/StrategyGroupDetail.vue`, add to the dialog form (after end_date):
```html
<label>起始资金(万): <input v-model.number="runCapital" type="number" min="1" step="1" /></label>
```

Add ref:
```javascript
const runCapital = ref(100)
```

Update `doRun` to pass `initial_capital: runCapital.value * 10000`:
```javascript
async function doRun() {
  showRunDialog.value = false
  const { data } = await runGroup(groupId, {
    start_date: runStartDate.value,
    end_date: runEndDate.value,
    execution_mode: runMode.value,
    initial_capital: runCapital.value * 10000,
  })
  // ...existing logic
}
```

- [ ] **Step 3: Update api/index.js if runGroup doesn't already pass body fields through**

Verify `runGroup` passes the full body object. It should already work if the function passes the body dict directly.

- [ ] **Step 4: Build frontend to verify no errors**

Run: `npm run build` (from frontend/)
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PipelineBuilder.vue frontend/src/views/StrategyGroupDetail.vue
git commit -m "feat: frontend buy/sell badges and initial_capital in run dialog"
```

---

### Task 10: Signal-table integration test with GroupRunner

**Files:**
- Test: `backend/tests/test_signal_table_integration.py`

- [ ] **Step 1: Write the integration test**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import tempfile
import pandas as pd
from unittest.mock import patch
from services.backtest.group_manager import GroupManager, GroupRunner
from services.backtest.task_manager import TaskManager


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        for i, d in enumerate(dates):
            p = base + i * 0.1
            rows.append({"date": d, "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000000, "amount": p * 1000000})
        data[sym] = pd.DataFrame(rows)
    return data


def test_signal_table_from_source_run():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        gm = GroupManager(db_path=db_path)
        tm = TaskManager(db_path=db_path)
        runner = GroupRunner(group_manager=gm, task_manager=tm)

        screener_group_id = gm.create_group("screener_group", [
            {"filepath": str(Path(tmp_dir) / "screener.py"), "class_name": "S", "params": {}}
        ])
        screener_run_id = gm.create_run(screener_group_id, "2024-01-02", "2024-01-22", "auto")
        screener_result = {
            "screened_symbols": [
                {"symbol": "000001", "match_dates": ["2024-01-05", "2024-01-10"]},
                {"symbol": "000002", "match_dates": ["2024-01-08"]},
            ]
        }
        gm.update_run_step(screener_run_id, 1, [{"step": 1, "symbols": ["000001", "000002"], "output_count": 2, "input_count": 0}])
        gm.update_run_status(screener_run_id, "success", final_result=screener_result)

        buyer_code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import BuyStrategy

class TestBuyer(BuyStrategy):
    name = "test"
    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if ctx.get_position(sym) is None:
                ctx.order_value(sym, 100000)
'''
        seller_code = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from services.backtest.base import SellStrategy

class TestSeller(SellStrategy):
    name = "test"
    def on_bar(self, ctx):
        pass
'''
        (Path(tmp_dir) / "buyer.py").write_text(buyer_code)
        (Path(tmp_dir) / "seller.py").write_text(seller_code)

        buy_sell_group_id = gm.create_group("buy_sell_group", [
            {"filepath": str(Path(tmp_dir) / "buyer.py"), "class_name": "TestBuyer", "params": {}},
            {"filepath": str(Path(tmp_dir) / "seller.py"), "class_name": "TestSeller", "params": {}},
        ])

        stock_data = _make_stock_data()
        with patch("services.backtest.group_manager.get_qfq_kline") as mock_kline, \
             patch("services.backtest.group_manager.RAW_KLINE_DIR") as mock_dir:
            mock_dir.glob.return_value = [Path(f"{s}.parquet") for s in stock_data.keys()]
            mock_kline.side_effect = lambda sym, **kw: stock_data.get(sym, pd.DataFrame())

            run_id = runner.run_auto(buy_sell_group_id, "2024-01-02", "2024-01-22", source_run_id=screener_run_id)

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        result = run["final_result"]
        assert "metrics" in result
        buy_trades = [t for t in result["trades"] if t["direction"] == "buy"]
        buy_dates = set(t["date"] for t in buy_trades)
        assert "2024-01-03" not in buy_dates
```

- [ ] **Step 2: Run test**

Run: `python -m pytest backend/tests/test_signal_table_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_signal_table_integration.py
git commit -m "test: integration test for signal-table mode with GroupRunner"
```

---

### Task 11: Run full test suite and final cleanup

- [ ] **Step 1: Run all backend tests**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All pass

- [ ] **Step 2: Build frontend**

Run: `npm run build` (from frontend/)
Expected: Build succeeds

- [ ] **Step 3: Final commit if any remaining changes**

```bash
git add -A
git commit -m "chore: buy/sell strategy system complete"
```
