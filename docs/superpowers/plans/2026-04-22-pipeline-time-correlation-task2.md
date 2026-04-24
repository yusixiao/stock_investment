### Task 2: 重写 `_run_screener_backtest` — 独立运行 + 逐对合并

**Files:**
- Modify: `backend/services/backtest/engine.py:120-172` (`_run_screener_backtest`)
- Modify: `backend/services/backtest/engine.py:1-9` (imports)
- Modify: `backend/tests/test_engine.py`

**Prerequisite:** Task 1 complete (date_utils.py exists), Task 5 complete (`self._join_modes` exists on engine). If doing Task 2 before Task 5, temporarily add `self._join_modes = getattr(self, '_join_modes', [])` at the top of `_run_screener_backtest`.

---

- [ ] **Step 1: Write failing tests for join_modes in screener backtest**

Append to `backend/tests/test_engine.py`:

```python
from services.backtest.date_utils import detect_frequency


class OddMonthScreener(ScreenerStrategy):
    name = "odd-month"
    description = ""
    params = {}
    frequency = "monthly"

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            price = ctx.get_price(sym)
            if price:
                month = int(price["date"][:7].split("-")[1])
                if month % 2 == 1:
                    result.append({"symbol": sym, "match_date": price["date"]})
        return result


class EvenMonthScreener(ScreenerStrategy):
    name = "even-month"
    description = ""
    params = {}
    frequency = "monthly"

    def screen(self, ctx, symbols):
        result = []
        for sym in symbols:
            price = ctx.get_price(sym)
            if price:
                month = int(price["date"][:7].split("-")[1])
                if month % 2 == 0:
                    result.append({"symbol": sym, "match_date": price["date"]})
        return result


class TestJoinModesScreenerBacktest:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
        }

    def test_independent_union_more_results(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener(), EvenMonthScreener()],
            trader=None,
            join_modes=["independent"],
        )
        result = engine.run()
        assert "screened_symbols" in result
        items = result["screened_symbols"]
        assert len(items) > 0
        for item in items:
            assert len(item["match_dates"]) > 0

    def test_correlated_intersection_no_overlap(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener(), EvenMonthScreener()],
            trader=None,
            join_modes=["correlated"],
        )
        result = engine.run()
        items = result.get("screened_symbols", [])
        total_dates = sum(len(item["match_dates"]) for item in items)
        assert total_dates == 0

    def test_default_join_modes_is_independent(self):
        data = self._make_data()
        engine_with = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), AlwaysPassScreener()],
            trader=None,
            join_modes=["independent"],
        )
        engine_without = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), AlwaysPassScreener()],
            trader=None,
        )
        r1 = engine_with.run()
        r2 = engine_without.run()
        dates1 = {item["symbol"]: sorted(item["match_dates"]) for item in r1["screened_symbols"]}
        dates2 = {item["symbol"]: sorted(item["match_dates"]) for item in r2["screened_symbols"]}
        assert dates1 == dates2

    def test_match_dates_use_frequency_format(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[OddMonthScreener()],
            trader=None,
        )
        result = engine.run()
        for item in result["screened_symbols"]:
            for d in item["match_dates"]:
                freq = detect_frequency(d)
                assert freq == "monthly", f"Expected monthly format, got {d} ({freq})"

    def test_mixed_freq_independent_finest_output(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), OddMonthScreener()],
            trader=None,
            join_modes=["independent"],
        )
        result = engine.run()
        for item in result["screened_symbols"]:
            for d in item["match_dates"]:
                freq = detect_frequency(d)
                assert freq == "daily", f"Expected daily (finest) format, got {d} ({freq})"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_engine.py::TestJoinModesScreenerBacktest -v`
Expected: FAIL — `BacktestEngine` doesn't accept `join_modes`

- [ ] **Step 3: Add `join_modes` to `BacktestEngine.__init__`**

In `backend/services/backtest/engine.py`, modify `__init__` (lines 25-43):

```python
class BacktestEngine:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        screeners: list[ScreenerStrategy],
        trader: TraderStrategy | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        join_modes: list[str] | None = None,
    ):
        self._stock_data = {}
        for sym, df in stock_data.items():
            self._stock_data[sym] = df.sort_values("date").reset_index(drop=True)

        self._screeners = screeners
        self._trader = trader
        self._all_symbols = list(self._stock_data.keys())
        self._on_progress = on_progress
        n = max(0, len(screeners) - 1)
        self._join_modes = (join_modes or [])[:n]
        while len(self._join_modes) < n:
            self._join_modes.append("independent")

        self._weekly_data: dict[str, pd.DataFrame] = {}
        self._monthly_data: dict[str, pd.DataFrame] = {}
        self._precompute_periods()
```

- [ ] **Step 4: Add imports for date_utils and logging**

In `backend/services/backtest/engine.py`, replace the imports at the top (lines 1-8):

```python
import logging
from typing import Callable

import pandas as pd
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.broker import Broker
from services.backtest.context import ScreenerContext, TraderContext
from services.backtest.analyzer import compute_metrics
from services.backtest.date_utils import format_match_date, date_belongs_to, detect_frequency, FREQ_ORDER
from services.stock_data import aggregate_kline

logger = logging.getLogger(__name__)
```

- [ ] **Step 5: Rewrite `_run_screener_backtest`**

Replace `_run_screener_backtest` (lines 120-172) with:

```python
    def _run_screener_backtest(self) -> dict:
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        n_bars = len(ref_df)
        n_screeners = len(self._screeners)

        raw_results: list[dict[str, list[str]]] = [{} for _ in range(n_screeners)]
        screener_cache: dict[int, list[str]] = {}
        prev_period_keys: dict[int, str] = {}
        custom_date_cache: dict[int, dict[str, str]] = {}

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "选股回测中")
            current_date = ref_df.iloc[idx]["date"]

            for si, screener in enumerate(self._screeners):
                freq = getattr(screener, "frequency", "daily")
                pk = self._period_key(current_date, freq)
                need_run = (si not in prev_period_keys) or (pk != prev_period_keys[si])

                if need_run:
                    ctx = self._make_screener_ctx(screener, idx)
                    raw_result = screener.screen(ctx, list(self._all_symbols))
                    symbols, custom_dates = _parse_screen_result(raw_result)
                    screener_cache[si] = list(symbols)
                    custom_date_cache[si] = custom_dates
                    prev_period_keys[si] = pk

                    record_date = self._period_date(current_date, freq)
                    if record_date is None:
                        continue
                    for sym in symbols:
                        raw_date = custom_dates.get(sym, record_date)
                        formatted = format_match_date(raw_date, freq)
                        logger.debug("[Format] %s(%s): %s match_date %r → %r", screener.__class__.__name__, freq, sym, raw_date, formatted)
                        history = raw_results[si].setdefault(sym, [])
                        if formatted not in history:
                            history.append(formatted)

        merged = dict(raw_results[0]) if raw_results else {}
        merged = {sym: list(dates) for sym, dates in merged.items()}

        for pair_idx in range(n_screeners - 1):
            join_mode = self._join_modes[pair_idx]
            next_result = raw_results[pair_idx + 1]
            prev_freq = self._finest_freq_in_result(merged)
            next_freq = getattr(self._screeners[pair_idx + 1], "frequency", "daily")

            if join_mode == "independent":
                merged = self._union_results(merged, next_result)
                logger.debug("[Pair %d] %s ∪ %s independent: prev=%d, next=%d, union=%d",
                    pair_idx, prev_freq, next_freq,
                    self._count_matches(raw_results[pair_idx] if pair_idx == 0 else merged),
                    self._count_matches(next_result),
                    self._count_matches(merged))
            else:
                coarse_freq = prev_freq if FREQ_ORDER.get(prev_freq, 0) > FREQ_ORDER.get(next_freq, 0) else next_freq
                prev_count = self._count_matches(merged)
                merged = self._intersect_results(merged, next_result, coarse_freq, pair_idx)
                logger.debug("[Pair %d] correlated(coarse=%s): prev=%d, next=%d, intersection=%d",
                    pair_idx, coarse_freq, prev_count,
                    self._count_matches(next_result),
                    self._count_matches(merged))

        finest = self._pipeline_finest_freq()
        final = self._filter_to_finest(merged, finest)

        result = []
        for sym, dates in final.items():
            if dates:
                result.append({"symbol": sym, "match_dates": dates})
        result.sort(key=lambda x: x["match_dates"][-1], reverse=True)
        return {"screened_symbols": result}
```

- [ ] **Step 6: Add helper methods to BacktestEngine**

Append these methods to the `BacktestEngine` class (before `_run_backtest`):

```python
    def _pipeline_finest_freq(self) -> str:
        finest = "yearly"
        for s in self._screeners:
            f = getattr(s, "frequency", "daily")
            if FREQ_ORDER.get(f, 0) < FREQ_ORDER.get(finest, 5):
                finest = f
        return finest

    def _finest_freq_in_result(self, result: dict[str, list[str]]) -> str:
        finest = "yearly"
        for dates in result.values():
            for d in dates:
                try:
                    f = detect_frequency(d)
                    if FREQ_ORDER.get(f, 0) < FREQ_ORDER.get(finest, 5):
                        finest = f
                except ValueError:
                    pass
        return finest

    def _count_matches(self, result: dict[str, list[str]]) -> int:
        return sum(len(dates) for dates in result.values())

    @staticmethod
    def _union_results(a: dict[str, list[str]], b: dict[str, list[str]]) -> dict[str, list[str]]:
        merged = {sym: list(dates) for sym, dates in a.items()}
        for sym, dates in b.items():
            existing = merged.setdefault(sym, [])
            for d in dates:
                if d not in existing:
                    existing.append(d)
        return merged

    @staticmethod
    def _intersect_results(prev: dict[str, list[str]], curr: dict[str, list[str]], coarse_freq: str, pair_idx: int) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        all_symbols = set(prev.keys()) & set(curr.keys())
        for sym in all_symbols:
            prev_dates = prev[sym]
            curr_dates = curr[sym]
            kept = []
            for pd_ in prev_dates:
                matched = False
                for cd in curr_dates:
                    pd_freq = detect_frequency(pd_)
                    cd_freq = detect_frequency(cd)
                    if FREQ_ORDER.get(pd_freq, 0) <= FREQ_ORDER.get(cd_freq, 0):
                        if date_belongs_to(pd_, cd):
                            matched = True
                            break
                    else:
                        if date_belongs_to(cd, pd_):
                            matched = True
                            break
                if matched:
                    kept.append(pd_)
                    logger.debug("[Pair %d] %s: %r matched in curr → keep", pair_idx, sym, pd_)
                else:
                    logger.debug("[Pair %d] %s: %r no match in curr → discard", pair_idx, sym, pd_)
            for cd in curr_dates:
                matched = False
                for pd_ in prev_dates:
                    pd_freq = detect_frequency(pd_)
                    cd_freq = detect_frequency(cd)
                    if FREQ_ORDER.get(cd_freq, 0) <= FREQ_ORDER.get(pd_freq, 0):
                        if date_belongs_to(cd, pd_):
                            matched = True
                            break
                    else:
                        if date_belongs_to(pd_, cd):
                            matched = True
                            break
                if matched and cd not in kept:
                    kept.append(cd)
            if kept:
                result[sym] = kept
        return result

    def _filter_to_finest(self, merged: dict[str, list[str]], finest: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for sym, dates in merged.items():
            kept = []
            for d in dates:
                try:
                    f = detect_frequency(d)
                except ValueError:
                    continue
                if f == finest:
                    kept.append(d)
                    logger.debug("[Output] %s: %r (%s) kept", sym, d, f)
                else:
                    logger.debug("[Output] %s: %r (%s) discarded — cannot refine to %s (pipeline finest=%s)", sym, d, f, finest, finest)
            if kept:
                result[sym] = kept
        return result
```

- [ ] **Step 7: Run new tests to verify they pass**

Run: `python -m pytest backend/tests/test_engine.py::TestJoinModesScreenerBacktest -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Run existing engine tests to verify no regression**

Run: `python -m pytest backend/tests/test_engine.py -v`
Expected: Some existing tests may need updates (handled in Task 6). New tests should PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/services/backtest/engine.py backend/tests/test_engine.py
git commit -m "feat: rewrite _run_screener_backtest with join_modes support"
```
