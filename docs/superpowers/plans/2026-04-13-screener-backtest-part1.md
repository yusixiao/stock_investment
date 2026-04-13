# Part 1: Backend Core — Base Classes, Strategy Loader, Broker (Tasks 1-3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

---

## Task 1: Strategy Base Classes + Config

**Files:**
- Create: `backend/services/backtest/__init__.py`
- Create: `backend/services/backtest/base.py`
- Modify: `backend/config.py`
- Test: `backend/tests/test_base_strategy.py`

### Steps

- [ ] **Step 1: Update config.py with new paths**

Add QFQ data dir and strategy dir to `backend/config.py`. Add after the existing `RAW_KLINE_DIR` line:

```python
QFQ_KLINE_DIR = DATA_DIR / "kline" / "A" / "qfq"
STRATEGY_DIR = BASE_DIR / "strategies"
```

- [ ] **Step 2: Create backtest package init**

Create `backend/services/backtest/__init__.py` as an empty file.

- [ ] **Step 3: Write failing tests for base classes**

Create `backend/tests/test_base_strategy.py`:

```python
import pytest
from services.backtest.base import (
    BaseStrategy,
    ScreenerStrategy,
    TraderStrategy,
    ParamAccessor,
)


class TestParamAccessor:
    def test_access_default_values(self):
        params = {"fast": {"default": 5}, "slow": {"default": 20}}
        p = ParamAccessor(params)
        assert p.fast == 5
        assert p.slow == 20

    def test_override_values(self):
        params = {"fast": {"default": 5}, "slow": {"default": 20}}
        p = ParamAccessor(params, overrides={"fast": 10})
        assert p.fast == 10
        assert p.slow == 20

    def test_missing_param_raises(self):
        p = ParamAccessor({"fast": {"default": 5}})
        with pytest.raises(AttributeError):
            _ = p.missing


class TestBaseStrategy:
    def test_has_required_attrs(self):
        class MyStrategy(BaseStrategy):
            name = "test"
            description = "desc"
            params = {"x": {"default": 1}}

        s = MyStrategy()
        assert s.name == "test"
        assert s.description == "desc"
        assert s.p.x == 1

    def test_with_overrides(self):
        class MyStrategy(BaseStrategy):
            name = "test"
            description = "desc"
            params = {"x": {"default": 1}}

        s = MyStrategy(param_overrides={"x": 99})
        assert s.p.x == 99

    def test_strategy_type(self):
        class MyStrategy(BaseStrategy):
            name = "test"
            description = ""
            params = {}

        s = MyStrategy()
        assert s.strategy_type == "base"


class TestScreenerStrategy:
    def test_strategy_type(self):
        class MyScreener(ScreenerStrategy):
            name = "test"
            description = ""
            params = {}
            def screen(self, ctx, symbols):
                return symbols

        s = MyScreener()
        assert s.strategy_type == "screener"

    def test_screen_must_be_implemented(self):
        class BadScreener(ScreenerStrategy):
            name = "test"
            description = ""
            params = {}

        s = BadScreener()
        with pytest.raises(NotImplementedError):
            s.screen(None, [])


class TestTraderStrategy:
    def test_strategy_type(self):
        class MyTrader(TraderStrategy):
            name = "test"
            description = ""
            params = {}
            settings = {"initial_capital": 1_000_000}
            def on_bar(self, ctx):
                pass

        s = MyTrader()
        assert s.strategy_type == "trader"
        assert s.settings["initial_capital"] == 1_000_000

    def test_on_bar_must_be_implemented(self):
        class BadTrader(TraderStrategy):
            name = "test"
            description = ""
            params = {}
            settings = {}

        s = BadTrader()
        with pytest.raises(NotImplementedError):
            s.on_bar(None)

    def test_default_settings(self):
        class MyTrader(TraderStrategy):
            name = "test"
            description = ""
            params = {}
            def on_bar(self, ctx):
                pass

        s = MyTrader()
        assert s.settings["initial_capital"] == 1_000_000
        assert s.settings["commission_rate"] == 0.0003
        assert s.settings["slippage"] == 0.002
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_base_strategy.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 5: Implement base classes**

Create `backend/services/backtest/base.py`:

```python
class ParamAccessor:
    def __init__(self, params: dict, overrides: dict = None):
        self._values = {}
        for key, conf in params.items():
            self._values[key] = conf["default"]
        if overrides:
            for key, val in overrides.items():
                if key in self._values:
                    self._values[key] = val

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._values:
            return self._values[name]
        raise AttributeError(f"No parameter named '{name}'")


class BaseStrategy:
    name: str = ""
    description: str = ""
    params: dict = {}
    strategy_type: str = "base"

    def __init__(self, param_overrides: dict = None):
        self.p = ParamAccessor(self.params, overrides=param_overrides)


class ScreenerStrategy(BaseStrategy):
    strategy_type = "screener"

    def screen(self, ctx, symbols: list[str]) -> list[str]:
        raise NotImplementedError


class TraderStrategy(BaseStrategy):
    strategy_type = "trader"
    settings: dict = {}

    def __init__(self, param_overrides: dict = None):
        super().__init__(param_overrides)
        defaults = {
            "initial_capital": 1_000_000,
            "commission_rate": 0.0003,
            "slippage": 0.002,
        }
        merged = {**defaults, **self.__class__.settings}
        self.settings = merged

    def on_bar(self, ctx):
        raise NotImplementedError
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_base_strategy.py -v`
Expected: All 9 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/services/backtest/ backend/tests/test_base_strategy.py
git commit -m "feat: strategy base classes (BaseStrategy, ScreenerStrategy, TraderStrategy)"
```

---

## Task 2: Strategy Loader

**Files:**
- Create: `backend/services/backtest/strategy_loader.py`
- Create: `strategies/examples/ma_cross_screener.py`
- Create: `strategies/examples/macd_screener.py`
- Create: `strategies/examples/equal_weight_trader.py`
- Test: `backend/tests/test_strategy_loader.py`

### Steps

- [ ] **Step 1: Create example strategy files**

Create `strategies/examples/ma_cross_screener.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class MaCrossScreener(ScreenerStrategy):
    name = "MA金叉选股"
    description = "选出短期MA上穿长期MA的股票"

    params = {
        "fast": {"default": 5},
        "slow": {"default": 20},
        "period": {"default": "monthly"},
    }

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            ma_f = ctx.indicator(sym, "ma", self.p.fast, period=self.p.period)
            ma_s = ctx.indicator(sym, "ma", self.p.slow, period=self.p.period)
            if ma_f is not None and ma_s is not None and ma_f > ma_s:
                result.append(sym)
        return result
```

Create `strategies/examples/macd_screener.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import ScreenerStrategy


class MacdScreener(ScreenerStrategy):
    name = "MACD强势选股"
    description = "选出DIF大于DEA的股票"

    params = {}

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            dif = ctx.indicator(sym, "macd", "dif")
            dea = ctx.indicator(sym, "macd", "dea")
            if dif is not None and dea is not None and dif > dea:
                result.append(sym)
        return result
```

Create `strategies/examples/equal_weight_trader.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from services.backtest.base import TraderStrategy


class EqualWeightTrader(TraderStrategy):
    name = "等权买入持有"
    description = "对筛选出的股票等权分配资金买入，定期调仓"

    params = {
        "rebalance_days": {"default": 20},
    }

    settings = {
        "initial_capital": 1_000_000,
        "commission_rate": 0.0003,
        "slippage": 0.002,
    }

    def on_bar(self, ctx):
        if ctx.days_since_rebalance >= self.p.rebalance_days:
            targets = ctx.selected_symbols
            target_pct = 1.0 / max(len(targets), 1)
            for sym in ctx.get_positions():
                if sym not in targets:
                    ctx.order_target_percent(sym, 0.0)
            for sym in targets:
                ctx.order_target_percent(sym, target_pct)
            ctx.reset_rebalance_counter()
```

- [ ] **Step 2: Write failing tests for strategy loader**

Create `backend/tests/test_strategy_loader.py`:

```python
import pytest
from pathlib import Path
from services.backtest.strategy_loader import (
    load_strategy_from_file,
    scan_strategies,
)
from services.backtest.base import ScreenerStrategy, TraderStrategy


EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "strategies" / "examples"


class TestLoadStrategyFromFile:
    def test_load_screener(self):
        filepath = EXAMPLES_DIR / "ma_cross_screener.py"
        strategies = load_strategy_from_file(filepath)
        assert len(strategies) >= 1
        s = strategies[0]
        assert isinstance(s, type)
        assert issubclass(s, ScreenerStrategy)
        assert s.name == "MA金叉选股"

    def test_load_trader(self):
        filepath = EXAMPLES_DIR / "equal_weight_trader.py"
        strategies = load_strategy_from_file(filepath)
        assert len(strategies) >= 1
        s = strategies[0]
        assert issubclass(s, TraderStrategy)
        assert s.name == "等权买入持有"

    def test_load_nonexistent_file(self):
        filepath = Path("/nonexistent/file.py")
        with pytest.raises(FileNotFoundError):
            load_strategy_from_file(filepath)

    def test_load_bad_syntax_file(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n")
        with pytest.raises(SyntaxError):
            load_strategy_from_file(bad)


class TestScanStrategies:
    def test_scan_examples_dir(self):
        results = scan_strategies(EXAMPLES_DIR)
        assert len(results) >= 3
        names = [r["name"] for r in results]
        assert "MA金叉选股" in names
        assert "等权买入持有" in names

    def test_scan_returns_correct_structure(self):
        results = scan_strategies(EXAMPLES_DIR)
        for r in results:
            assert "name" in r
            assert "description" in r
            assert "strategy_type" in r
            assert "params" in r
            assert "filepath" in r
            assert r["strategy_type"] in ("screener", "trader")

    def test_scan_empty_dir(self, tmp_path):
        results = scan_strategies(tmp_path)
        assert results == []

    def test_scan_skips_bad_files(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n")
        results = scan_strategies(tmp_path)
        assert results == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_strategy_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement strategy loader**

Create `backend/services/backtest/strategy_loader.py`:

```python
import importlib.util
import inspect
from pathlib import Path

from services.backtest.base import BaseStrategy, ScreenerStrategy, TraderStrategy


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
            and obj not in (BaseStrategy, ScreenerStrategy, TraderStrategy)
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
            results.append({
                "name": cls.name,
                "description": cls.description,
                "strategy_type": cls.strategy_type,
                "params": cls.params,
                "filepath": str(filepath),
                "class_name": cls.__name__,
            })
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_strategy_loader.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add strategies/ backend/services/backtest/strategy_loader.py backend/tests/test_strategy_loader.py
git commit -m "feat: strategy loader with importlib and example strategies"
```

---

## Task 3: Broker + Portfolio

**Files:**
- Create: `backend/services/backtest/broker.py`
- Create: `backend/services/backtest/portfolio.py`
- Test: `backend/tests/test_broker.py`

### Steps

- [ ] **Step 1: Write failing tests for Broker and Portfolio**

Create `backend/tests/test_broker.py`:

```python
import pytest
from services.backtest.broker import Broker, Order
from services.backtest.portfolio import Portfolio


class TestPortfolio:
    def test_initial_state(self):
        p = Portfolio(initial_capital=1_000_000)
        assert p.cash == 1_000_000
        assert p.get_total_value({}) == 1_000_000
        assert p.get_positions() == []

    def test_buy_updates_position(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=1800.0, commission=54.0, date="2024-01-15")
        pos = p.get_position("600519.SH")
        assert pos is not None
        assert pos["shares"] == 100
        assert pos["cost"] == 1800.0
        assert p.cash == 1_000_000 - 100 * 1800.0 - 54.0

    def test_sell_updates_position(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=1800.0, commission=54.0, date="2024-01-15")
        p.sell("600519.SH", shares=100, price=1900.0, commission=57.0, tax=190.0)
        pos = p.get_position("600519.SH")
        assert pos is None
        assert p.get_positions() == []

    def test_sell_partial(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=200, price=100.0, commission=5.0, date="2024-01-15")
        p.sell("600519.SH", shares=100, price=110.0, commission=5.0, tax=11.0)
        pos = p.get_position("600519.SH")
        assert pos["shares"] == 100

    def test_total_value_with_positions(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=100.0, commission=5.0, date="2024-01-15")
        prices = {"600519.SH": 110.0}
        total = p.get_total_value(prices)
        expected = p.cash + 100 * 110.0
        assert total == expected

    def test_snapshot(self):
        p = Portfolio(initial_capital=1_000_000)
        p.buy("600519.SH", shares=100, price=100.0, commission=5.0, date="2024-01-15")
        snap = p.snapshot("2024-01-15", {"600519.SH": 105.0})
        assert snap["date"] == "2024-01-15"
        assert snap["cash"] == p.cash
        assert snap["market_value"] == 100 * 105.0
        assert snap["total_value"] == p.cash + 100 * 105.0


class TestBroker:
    def _make_broker(self, capital=1_000_000, commission_rate=0.0003, slippage=0.002):
        return Broker(
            initial_capital=capital,
            commission_rate=commission_rate,
            slippage=slippage,
        )

    def test_submit_buy_order(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        assert len(b.pending_orders) == 1
        assert b.pending_orders[0].direction == "buy"

    def test_fill_buy_order(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        prev_close = 95.0
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": prev_close})
        assert len(trades) == 1
        assert trades[0]["direction"] == "buy"
        assert trades[0]["shares"] == 100

    def test_commission_minimum_5(self):
        b = self._make_broker(commission_rate=0.0003)
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 10.0, "close": 10.0, "high": 10.0, "low": 10.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 9.5})
        assert trades[0]["commission"] == 5.0

    def test_sell_includes_tax(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 110.0, "close": 110.0, "high": 115.0, "low": 105.0}
        trades = b.fill_orders("2024-01-17", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trade = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trade) == 1
        assert sell_trade[0]["tax"] > 0

    def test_t_plus_1_rejects_same_day_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 105.0, "close": 105.0, "high": 110.0, "low": 100.0}
        trades = b.fill_orders("2024-01-15", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 0

    def test_t_plus_1_allows_next_day_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        bar2 = {"open": 105.0, "close": 105.0, "high": 110.0, "low": 100.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar2}, {"600519.SH": 100.0})
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 1

    def test_limit_up_rejects_buy(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        prev_close = 100.0
        limit_up = round(prev_close * 1.1, 2)
        bar = {"open": limit_up, "close": limit_up, "high": limit_up, "low": limit_up}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": prev_close})
        assert len(trades) == 0

    def test_limit_down_rejects_sell(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        b.fill_orders("2024-01-15", {"600519.SH": bar}, {"600519.SH": 95.0})
        b.submit_order("600519.SH", shares=100, direction="sell")
        prev_close = 100.0
        limit_down = round(prev_close * 0.9, 2)
        bar2 = {"open": limit_down, "close": limit_down, "high": limit_down, "low": limit_down}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar2}, {"600519.SH": prev_close})
        sell_trades = [t for t in trades if t["direction"] == "sell"]
        assert len(sell_trades) == 0

    def test_buy_rounds_to_100_shares(self):
        b = self._make_broker()
        b.submit_order("600519.SH", shares=150, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        assert trades[0]["shares"] == 100

    def test_slippage_applied(self):
        b = self._make_broker(slippage=0.01)
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        mid_price = (100.0 + 100.0) / 2
        expected_price = mid_price * (1 + 0.01)
        assert abs(trades[0]["price"] - expected_price) < 0.01

    def test_insufficient_funds_rejects(self):
        b = self._make_broker(capital=1000)
        b.submit_order("600519.SH", shares=100, direction="buy")
        bar = {"open": 100.0, "close": 100.0, "high": 110.0, "low": 90.0}
        trades = b.fill_orders("2024-01-16", {"600519.SH": bar}, {"600519.SH": 95.0})
        assert len(trades) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_broker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Portfolio**

Create `backend/services/backtest/portfolio.py`:

```python
from dataclasses import dataclass, field


@dataclass
class PositionInfo:
    shares: int = 0
    cost: float = 0.0
    buy_date: str = ""


class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self._positions: dict[str, PositionInfo] = {}

    def buy(self, symbol: str, shares: int, price: float, commission: float, date: str):
        total_cost = shares * price + commission
        self.cash -= total_cost
        if symbol in self._positions:
            pos = self._positions[symbol]
            old_total = pos.shares * pos.cost
            new_total = old_total + shares * price
            pos.shares += shares
            pos.cost = new_total / pos.shares if pos.shares > 0 else 0.0
            pos.buy_date = date
        else:
            self._positions[symbol] = PositionInfo(
                shares=shares, cost=price, buy_date=date
            )

    def sell(self, symbol: str, shares: int, price: float, commission: float, tax: float):
        total_income = shares * price - commission - tax
        self.cash += total_income
        if symbol in self._positions:
            self._positions[symbol].shares -= shares
            if self._positions[symbol].shares <= 0:
                del self._positions[symbol]

    def get_position(self, symbol: str) -> dict | None:
        if symbol not in self._positions:
            return None
        pos = self._positions[symbol]
        return {"shares": pos.shares, "cost": pos.cost, "buy_date": pos.buy_date}

    def get_positions(self) -> list[str]:
        return list(self._positions.keys())

    def get_total_value(self, current_prices: dict[str, float]) -> float:
        market_value = sum(
            pos.shares * current_prices.get(sym, pos.cost)
            for sym, pos in self._positions.items()
        )
        return self.cash + market_value

    def get_market_value(self, current_prices: dict[str, float]) -> float:
        return sum(
            pos.shares * current_prices.get(sym, pos.cost)
            for sym, pos in self._positions.items()
        )

    def snapshot(self, date: str, current_prices: dict[str, float]) -> dict:
        market_value = self.get_market_value(current_prices)
        total_value = self.cash + market_value
        positions = {}
        for sym, pos in self._positions.items():
            positions[sym] = {
                "shares": pos.shares,
                "cost": pos.cost,
                "market_price": current_prices.get(sym, pos.cost),
            }
        return {
            "date": date,
            "total_value": total_value,
            "cash": self.cash,
            "market_value": market_value,
            "positions": positions,
        }
```

- [ ] **Step 4: Implement Broker**

Create `backend/services/backtest/broker.py`:

```python
from dataclasses import dataclass, field
from services.backtest.portfolio import Portfolio


@dataclass
class Order:
    symbol: str
    shares: int
    direction: str  # "buy" or "sell"
    status: str = "pending"


class Broker:
    def __init__(
        self,
        initial_capital: float = 1_000_000,
        commission_rate: float = 0.0003,
        slippage: float = 0.002,
    ):
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.portfolio = Portfolio(initial_capital)
        self.pending_orders: list[Order] = []
        self.all_trades: list[dict] = []

    def submit_order(self, symbol: str, shares: int, direction: str):
        self.pending_orders.append(Order(symbol=symbol, shares=shares, direction=direction))

    def fill_orders(
        self,
        date: str,
        bars: dict[str, dict],
        prev_closes: dict[str, float],
    ) -> list[dict]:
        trades = []
        remaining = []
        for order in self.pending_orders:
            bar = bars.get(order.symbol)
            if bar is None:
                remaining.append(order)
                continue
            prev_close = prev_closes.get(order.symbol)
            trade = self._try_fill(order, bar, prev_close, date)
            if trade is not None:
                trades.append(trade)
            # rejected orders are dropped
        self.pending_orders = remaining
        self.all_trades.extend(trades)
        return trades

    def _try_fill(self, order: Order, bar: dict, prev_close: float | None, date: str) -> dict | None:
        mid_price = (bar["open"] + bar["close"]) / 2

        if prev_close is not None:
            limit_up = round(prev_close * 1.1, 2)
            limit_down = round(prev_close * 0.9, 2)
            is_limit_up = (bar["low"] == bar["high"] == limit_up)
            is_limit_down = (bar["low"] == bar["high"] == limit_down)
            if order.direction == "buy" and is_limit_up:
                return None
            if order.direction == "sell" and is_limit_down:
                return None

        if order.direction == "buy":
            fill_price = mid_price * (1 + self.slippage)
            shares = (order.shares // 100) * 100
            if shares <= 0:
                return None
            commission = max(shares * fill_price * self.commission_rate, 5.0)
            total_cost = shares * fill_price + commission
            if total_cost > self.portfolio.cash:
                return None
            self.portfolio.buy(order.symbol, shares, fill_price, commission, date)
            return {
                "date": date,
                "symbol": order.symbol,
                "direction": "buy",
                "price": fill_price,
                "shares": shares,
                "commission": commission,
                "tax": 0.0,
                "amount": shares * fill_price,
            }

        elif order.direction == "sell":
            pos = self.portfolio.get_position(order.symbol)
            if pos is None:
                return None
            if pos["buy_date"] >= date:
                return None
            sell_shares = min(order.shares, pos["shares"])
            if sell_shares <= 0:
                return None
            fill_price = mid_price * (1 - self.slippage)
            commission = max(sell_shares * fill_price * self.commission_rate, 5.0)
            tax = sell_shares * fill_price * 0.001
            self.portfolio.sell(order.symbol, sell_shares, fill_price, commission, tax)
            return {
                "date": date,
                "symbol": order.symbol,
                "direction": "sell",
                "price": fill_price,
                "shares": sell_shares,
                "commission": commission,
                "tax": tax,
                "amount": sell_shares * fill_price,
            }

        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_broker.py -v`
Expected: All 17 tests PASS

- [ ] **Step 6: Run all tests to ensure no regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS (37 old + 9 base + 8 loader + 17 broker = 71)

- [ ] **Step 7: Commit**

```bash
git add backend/services/backtest/broker.py backend/services/backtest/portfolio.py backend/tests/test_broker.py
git commit -m "feat: Broker with T+1, limit-up/down, commission, slippage and Portfolio tracker"
```
