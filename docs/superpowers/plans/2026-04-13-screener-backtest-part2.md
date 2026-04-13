# Part 2: Backend Engine — Context, Engine, Analyzer (Tasks 4-6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

---

## Task 4: Context Objects

**Files:**
- Create: `backend/services/backtest/context.py`
- Test: `backend/tests/test_context.py`

### Steps

- [ ] **Step 1: Write failing tests for Context**

Create `backend/tests/test_context.py`:

```python
import pytest
import pandas as pd
import numpy as np
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.portfolio import Portfolio


def _make_stock_data():
    n = 60
    np.random.seed(42)
    close = 10 + np.cumsum(np.random.randn(n) * 0.5)
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    df = pd.DataFrame({
        "date": dates,
        "open": close + np.random.randn(n) * 0.1,
        "high": close + np.abs(np.random.randn(n) * 0.3),
        "low": close - np.abs(np.random.randn(n) * 0.3),
        "close": close,
        "volume": np.random.randint(1e6, 1e7, n).astype(float),
        "amount": np.random.randint(1e7, 1e8, n).astype(float),
    })
    return df


class TestScreenerContext:
    def test_get_price(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        price = ctx.get_price("600519.SH")
        assert "open" in price
        assert "close" in price
        assert "date" in price

    def test_get_price_missing_symbol(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        price = ctx.get_price("MISSING.SH")
        assert price is None

    def test_indicator_ma(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        val = ctx.indicator("600519.SH", "ma", 5)
        assert val is not None
        assert isinstance(val, float)

    def test_indicator_macd(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        dif = ctx.indicator("600519.SH", "macd", "dif")
        dea = ctx.indicator("600519.SH", "macd", "dea")
        assert dif is not None
        assert dea is not None

    def test_indicator_missing_symbol(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        val = ctx.indicator("MISSING.SH", "ma", 5)
        assert val is None

    def test_indicator_caching(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        val1 = ctx.indicator("600519.SH", "ma", 5)
        val2 = ctx.indicator("600519.SH", "ma", 5)
        assert val1 == val2

    def test_current_date(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=10)
        assert ctx.current_date == data["600519.SH"].iloc[10]["date"]

    def test_get_history(self):
        data = {"600519.SH": _make_stock_data()}
        ctx = ScreenerContext(stock_data=data, current_idx=30)
        history = ctx.get_history("600519.SH", 5)
        assert len(history) == 5


class TestTraderContext:
    def test_has_screener_methods(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=["600519.SH"],
        )
        assert ctx.get_price("600519.SH") is not None
        assert ctx.current_date is not None

    def test_selected_symbols(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=["600519.SH"],
        )
        assert ctx.selected_symbols == ["600519.SH"]

    def test_get_portfolio(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=[],
        )
        p = ctx.get_portfolio()
        assert p["cash"] == 1_000_000
        assert p["total_value"] == 1_000_000

    def test_order_target_percent_generates_order(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        orders = []
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda sym, shares, d: orders.append((sym, shares, d)),
            selected_symbols=["600519.SH"],
        )
        ctx.order_target_percent("600519.SH", 0.5)
        assert len(orders) == 1
        assert orders[0][0] == "600519.SH"
        assert orders[0][2] == "buy"

    def test_rebalance_counter(self):
        data = {"600519.SH": _make_stock_data()}
        portfolio = Portfolio(1_000_000)
        ctx = TraderContext(
            stock_data=data, current_idx=30,
            portfolio=portfolio, broker_submit=lambda *a: None,
            selected_symbols=[],
            days_since_rebalance=15,
        )
        assert ctx.days_since_rebalance == 15
        ctx.reset_rebalance_counter()
        assert ctx.days_since_rebalance == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Context**

Create `backend/services/backtest/context.py`:

```python
import math
import pandas as pd
from services.indicator import calc_ma, calc_macd, calc_kdj, calc_boll
from services.stock_data import aggregate_kline
from services.backtest.portfolio import Portfolio


class ScreenerContext:
    def __init__(self, stock_data: dict[str, pd.DataFrame], current_idx: int):
        self._stock_data = stock_data
        self._current_idx = current_idx
        self._indicator_cache: dict[str, pd.DataFrame] = {}
        ref_sym = next(iter(stock_data))
        self._current_date = stock_data[ref_sym].iloc[current_idx]["date"]

    @property
    def current_date(self) -> str:
        return self._current_date

    def get_price(self, symbol: str) -> dict | None:
        if symbol not in self._stock_data:
            return None
        df = self._stock_data[symbol]
        if self._current_idx >= len(df):
            return None
        row = df.iloc[self._current_idx]
        return row.to_dict()

    def get_history(self, symbol: str, n: int) -> list[dict]:
        if symbol not in self._stock_data:
            return []
        df = self._stock_data[symbol]
        start = max(0, self._current_idx - n + 1)
        end = self._current_idx + 1
        return df.iloc[start:end].to_dict(orient="records")

    def indicator(self, symbol: str, ind_type: str, *args, period: str = "daily") -> float | None:
        if symbol not in self._stock_data:
            return None
        df = self._stock_data[symbol]
        data_up_to = df.iloc[: self._current_idx + 1]
        if len(data_up_to) < 2:
            return None

        if period in ("weekly", "monthly"):
            cache_key = f"{symbol}_{period}_agg"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = aggregate_kline(data_up_to, period=period)
            data_up_to = self._indicator_cache[cache_key]
            if len(data_up_to) < 2:
                return None

        if ind_type == "ma":
            window = args[0] if args else 5
            cache_key = f"{symbol}_{period}_ma_{window}"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_ma(data_up_to, windows=[window])
            result_df = self._indicator_cache[cache_key]
            col = f"ma{window}"
            if col not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[col].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "macd":
            field_name = args[0] if args else "dif"
            cache_key = f"{symbol}_{period}_macd"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_macd(data_up_to)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "kdj":
            field_name = args[0] if args else "k"
            cache_key = f"{symbol}_{period}_kdj"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_kdj(data_up_to)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        elif ind_type == "boll":
            field_name = args[0] if args else "boll_mid"
            cache_key = f"{symbol}_{period}_boll"
            if cache_key not in self._indicator_cache:
                self._indicator_cache[cache_key] = calc_boll(data_up_to)
            result_df = self._indicator_cache[cache_key]
            if field_name not in result_df.columns:
                return None
            sorted_df = result_df.sort_values("date")
            val = sorted_df[field_name].iloc[-1]
            return None if (isinstance(val, float) and math.isnan(val)) else float(val)

        return None


class TraderContext(ScreenerContext):
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        current_idx: int,
        portfolio: Portfolio,
        broker_submit,
        selected_symbols: list[str],
        days_since_rebalance: int = 0,
    ):
        super().__init__(stock_data, current_idx)
        self._portfolio = portfolio
        self._broker_submit = broker_submit
        self.selected_symbols = selected_symbols
        self.days_since_rebalance = days_since_rebalance

    def reset_rebalance_counter(self):
        self.days_since_rebalance = 0

    def get_position(self, symbol: str) -> dict | None:
        return self._portfolio.get_position(symbol)

    def get_positions(self) -> list[str]:
        return self._portfolio.get_positions()

    def get_portfolio(self) -> dict:
        prices = {}
        for sym in self._portfolio.get_positions():
            p = self.get_price(sym)
            if p:
                prices[sym] = p["close"]
        return {
            "cash": self._portfolio.cash,
            "total_value": self._portfolio.get_total_value(prices),
            "market_value": self._portfolio.get_market_value(prices),
        }

    def order_target_percent(self, symbol: str, percent: float):
        prices = {}
        for sym in self._portfolio.get_positions():
            p = self.get_price(sym)
            if p:
                prices[sym] = p["close"]
        total_value = self._portfolio.get_total_value(prices)
        target_value = total_value * percent
        current_price = self.get_price(symbol)
        if current_price is None:
            return
        pos = self._portfolio.get_position(symbol)
        current_value = (pos["shares"] * current_price["close"]) if pos else 0.0
        diff_value = target_value - current_value
        if abs(diff_value) < current_price["close"]:
            return
        shares = int(abs(diff_value) / current_price["close"])
        if diff_value > 0:
            self._broker_submit(symbol, shares, "buy")
        else:
            self._broker_submit(symbol, shares, "sell")

    def order_shares(self, symbol: str, shares: int):
        if shares > 0:
            self._broker_submit(symbol, shares, "buy")
        elif shares < 0:
            self._broker_submit(symbol, -shares, "sell")

    def order_value(self, symbol: str, value: float):
        current_price = self.get_price(symbol)
        if current_price is None:
            return
        shares = int(abs(value) / current_price["close"])
        if value > 0:
            self._broker_submit(symbol, shares, "buy")
        elif value < 0:
            self._broker_submit(symbol, shares, "sell")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_context.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/context.py backend/tests/test_context.py
git commit -m "feat: ScreenerContext and TraderContext with indicator caching"
```

---

## Task 5: Backtest Engine

**Files:**
- Create: `backend/services/backtest/engine.py`
- Test: `backend/tests/test_engine.py`

### Steps

- [ ] **Step 1: Write failing tests for Engine**

Create `backend/tests/test_engine.py`:

```python
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy, TraderStrategy


def _make_stock_df(n=100, seed=42, base_price=100.0):
    np.random.seed(seed)
    close = base_price + np.cumsum(np.random.randn(n) * 1.0)
    close = np.maximum(close, 1.0)
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    return pd.DataFrame({
        "date": dates,
        "open": close + np.random.randn(n) * 0.5,
        "high": close + np.abs(np.random.randn(n) * 1.0),
        "low": close - np.abs(np.random.randn(n) * 1.0),
        "close": close,
        "volume": np.random.randint(1e6, 1e7, n).astype(float),
        "amount": np.random.randint(1e7, 1e8, n).astype(float),
    })


class AlwaysPassScreener(ScreenerStrategy):
    name = "pass-all"
    description = ""
    params = {}

    def screen(self, ctx, symbols):
        return symbols


class TopOneScreener(ScreenerStrategy):
    name = "top-one"
    description = ""
    params = {}

    def screen(self, ctx, symbols):
        return symbols[:1]


class BuyAndHoldTrader(TraderStrategy):
    name = "buy-hold"
    description = ""
    params = {}
    settings = {"initial_capital": 100_000, "commission_rate": 0.0003, "slippage": 0.0}

    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if not ctx.get_position(sym):
                ctx.order_target_percent(sym, 0.9)


class TestBacktestEngine:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
        }

    def test_screener_only_returns_symbols(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        assert len(result["screened_symbols"]) > 0

    def test_screener_chain(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), TopOneScreener()],
            trader=None,
        )
        result = engine.run()
        assert len(result["screened_symbols"]) == 1

    def test_full_backtest_returns_metrics(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert "metrics" in result
        assert "total_return" in result["metrics"]
        assert "equity_curve" in result
        assert "trades" in result

    def test_equity_curve_has_entries(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert len(result["equity_curve"]) > 0
        assert "date" in result["equity_curve"][0]
        assert "total_value" in result["equity_curve"][0]

    def test_trades_have_correct_fields(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        if result["trades"]:
            t = result["trades"][0]
            assert "date" in t
            assert "symbol" in t
            assert "direction" in t
            assert "price" in t
            assert "shares" in t

    def test_empty_screener_result(self):
        class EmptyScreener(ScreenerStrategy):
            name = "empty"
            description = ""
            params = {}
            def screen(self, ctx, symbols):
                return []

        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[EmptyScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert result["trades"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement BacktestEngine**

Create `backend/services/backtest/engine.py`:

```python
import pandas as pd
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.broker import Broker
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.analyzer import compute_metrics


class BacktestEngine:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy],
        trader: TraderStrategy | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners
        self._trader = trader
        self._all_symbols = list(self._stock_data.keys())

    def run(self) -> dict:
        if self._trader is None:
            return self._run_screener_only()
        return self._run_backtest()

    def _run_screener_only(self) -> dict:
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        last_idx = len(ref_df) - 1
        symbols = list(self._all_symbols)
        for screener in self._screeners:
            ctx = ScreenerContext(self._stock_data, last_idx)
            symbols = screener.screen(ctx, symbols)
        return {"screened_symbols": symbols}

    def _run_backtest(self) -> dict:
        settings = self._trader.settings
        broker = Broker(
            initial_capital=settings["initial_capital"],
            commission_rate=settings["commission_rate"],
            slippage=settings["slippage"],
        )

        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)

        equity_curve = []
        days_since_rebalance = 0
        prev_closes: dict[str, float] = {}

        for idx in range(n_bars):
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
                broker.fill_orders(ref_df.iloc[idx]["date"], current_bars, prev_closes)

            available_symbols = [s for s in self._all_symbols if s in current_bars]
            symbols = list(available_symbols)
            for screener in self._screeners:
                ctx = ScreenerContext(self._stock_data, idx)
                symbols = screener.screen(ctx, symbols)

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=symbols,
                days_since_rebalance=days_since_rebalance,
            )

            try:
                self._trader.on_bar(trader_ctx)
            except Exception:
                pass

            days_since_rebalance = trader_ctx.days_since_rebalance + 1

            snap = broker.portfolio.snapshot(ref_df.iloc[idx]["date"], current_prices)
            equity_curve.append(snap)

            prev_closes = dict(current_prices)

        metrics = compute_metrics(equity_curve, broker.all_trades, settings["initial_capital"])

        return {
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": broker.all_trades,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_engine.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/engine.py backend/tests/test_engine.py
git commit -m "feat: BacktestEngine with event-driven main loop and screener pipeline"
```

---

## Task 6: Performance Analyzer

**Files:**
- Create: `backend/services/backtest/analyzer.py`
- Test: `backend/tests/test_analyzer.py`

### Steps

- [ ] **Step 1: Write failing tests for Analyzer**

Create `backend/tests/test_analyzer.py`:

```python
import pytest
from services.backtest.analyzer import compute_metrics


class TestComputeMetrics:
    def _make_equity_curve(self, values):
        import pandas as pd
        dates = pd.date_range("2024-01-01", periods=len(values), freq="B").strftime("%Y-%m-%d").tolist()
        return [{"date": d, "total_value": v, "cash": v * 0.5, "market_value": v * 0.5} for d, v in zip(dates, values)]

    def test_basic_positive_return(self):
        curve = self._make_equity_curve([100_000, 105_000, 110_000, 115_000, 120_000])
        trades = [
            {"direction": "buy", "shares": 100, "price": 100, "amount": 10000},
            {"direction": "sell", "shares": 100, "price": 120, "amount": 12000},
        ]
        m = compute_metrics(curve, trades, initial_capital=100_000)
        assert m["total_return"] == pytest.approx(0.2, abs=0.01)
        assert m["trade_count"] == 2

    def test_max_drawdown(self):
        curve = self._make_equity_curve([100_000, 110_000, 90_000, 95_000])
        m = compute_metrics(curve, [], initial_capital=100_000)
        expected_dd = (110_000 - 90_000) / 110_000
        assert m["max_drawdown"] == pytest.approx(expected_dd, abs=0.01)

    def test_win_rate(self):
        trades = [
            {"direction": "sell", "shares": 100, "price": 120, "amount": 12000},
            {"direction": "sell", "shares": 100, "price": 80, "amount": 8000},
            {"direction": "buy", "shares": 100, "price": 100, "amount": 10000},
            {"direction": "buy", "shares": 100, "price": 100, "amount": 10000},
        ]
        curve = self._make_equity_curve([100_000, 100_000])
        m = compute_metrics(curve, trades, initial_capital=100_000)
        assert "win_rate" in m

    def test_no_trades(self):
        curve = self._make_equity_curve([100_000, 100_000, 100_000])
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert m["total_return"] == 0.0
        assert m["trade_count"] == 0
        assert m["win_rate"] == 0.0

    def test_annualized_return(self):
        values = [100_000 + i * 100 for i in range(253)]
        curve = self._make_equity_curve(values)
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert m["annualized_return"] > 0

    def test_sharpe_ratio(self):
        values = [100_000 + i * 50 for i in range(100)]
        curve = self._make_equity_curve(values)
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert "sharpe_ratio" in m

    def test_single_day(self):
        curve = self._make_equity_curve([100_000])
        m = compute_metrics(curve, [], initial_capital=100_000)
        assert m["total_return"] == 0.0
        assert m["max_drawdown"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Analyzer**

Create `backend/services/backtest/analyzer.py`:

```python
import math
from datetime import datetime


def compute_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    initial_capital: float,
) -> dict:
    if not equity_curve:
        return _empty_metrics()

    values = [e["total_value"] for e in equity_curve]
    dates = [e["date"] for e in equity_curve]

    final_value = values[-1]
    total_return = (final_value - initial_capital) / initial_capital

    if len(dates) >= 2:
        start_dt = datetime.strptime(dates[0], "%Y-%m-%d")
        end_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
        years = (end_dt - start_dt).days / 365.25
    else:
        years = 0

    if years > 0 and total_return > -1:
        annualized_return = (1 + total_return) ** (1 / years) - 1
    else:
        annualized_return = 0.0

    max_drawdown = _calc_max_drawdown(values)

    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append((values[i] - values[i - 1]) / values[i - 1])

    sharpe_ratio = _calc_sharpe(daily_returns, risk_free_rate=0.03)

    sell_trades = [t for t in trades if t["direction"] == "sell"]
    buy_trades = [t for t in trades if t["direction"] == "buy"]

    win_count = 0
    total_profit = 0.0
    total_loss = 0.0
    win_profits = 0.0
    loss_profits = 0.0
    for i, sell in enumerate(sell_trades):
        if i < len(buy_trades):
            pnl = (sell["price"] - buy_trades[i]["price"]) * sell["shares"]
            if pnl > 0:
                win_count += 1
                win_profits += pnl
            else:
                loss_profits += abs(pnl)

    trade_count = len(trades)
    n_round_trips = min(len(sell_trades), len(buy_trades))
    win_rate = win_count / n_round_trips if n_round_trips > 0 else 0.0
    profit_loss_ratio = (win_profits / win_count) / (loss_profits / (n_round_trips - win_count)) if (n_round_trips > win_count > 0 and loss_profits > 0) else 0.0

    total_trade_amount = sum(t.get("amount", 0) for t in trades)
    avg_daily_turnover = total_trade_amount / len(values) if values else 0
    avg_daily_value = sum(values) / len(values) if values else 1
    daily_turnover_rate = avg_daily_turnover / avg_daily_value if avg_daily_value > 0 else 0

    return {
        "total_return": round(total_return, 6),
        "annualized_return": round(annualized_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "trade_count": trade_count,
        "daily_turnover_rate": round(daily_turnover_rate, 6),
    }


def _calc_max_drawdown(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _calc_sharpe(daily_returns: list[float], risk_free_rate: float = 0.03) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean_r = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0
    annual_return = mean_r * 252
    annual_std = std_r * math.sqrt(252)
    return (annual_return - risk_free_rate) / annual_std


def _empty_metrics() -> dict:
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "win_rate": 0.0,
        "profit_loss_ratio": 0.0,
        "trade_count": 0,
        "daily_turnover_rate": 0.0,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_analyzer.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run all tests to ensure no regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/analyzer.py backend/tests/test_analyzer.py
git commit -m "feat: performance analyzer with return, drawdown, Sharpe, win rate"
```
