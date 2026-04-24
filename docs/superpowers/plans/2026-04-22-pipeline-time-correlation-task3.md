### Task 3: 重写 `_run_screener_only` — 独立运行 + 逐对合并(实时选股模式)

**Files:**
- Modify: `backend/services/backtest/engine.py:83-94` (`_run_screener_only`)
- Modify: `backend/tests/test_engine.py`

**Prerequisite:** Task 2 complete (helper methods `_union_results` etc. exist on engine)

---

- [ ] **Step 1: Write failing tests for join_modes in screener-only mode**

Append to `backend/tests/test_engine.py`:

```python
class FirstHalfScreener(ScreenerStrategy):
    name = "first-half"
    description = ""
    params = {}

    def screen(self, ctx, symbols):
        return symbols[:len(symbols) // 2]


class SecondHalfScreener(ScreenerStrategy):
    name = "second-half"
    description = ""
    params = {}

    def screen(self, ctx, symbols):
        return symbols[len(symbols) // 2:]


class TestJoinModesScreenerOnly:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
            "CCC.SZ": _make_stock_df(100, seed=44, base_price=80.0),
            "DDD.SH": _make_stock_df(100, seed=45, base_price=60.0),
        }

    def test_independent_union_screen_mode(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=None,
            join_modes=["independent"],
        )
        result = engine.run(mode="screen")
        assert set(result["screened_symbols"]) == set(data.keys())

    def test_correlated_intersection_screen_mode(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=None,
            join_modes=["correlated"],
        )
        result = engine.run(mode="screen")
        assert len(result["screened_symbols"]) == 0

    def test_correlated_overlap_screen_mode(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), FirstHalfScreener()],
            trader=None,
            join_modes=["correlated"],
        )
        result = engine.run(mode="screen")
        assert len(result["screened_symbols"]) == len(data) // 2

    def test_default_independent_screen_mode(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=None,
        )
        result = engine.run(mode="screen")
        assert set(result["screened_symbols"]) == set(data.keys())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_engine.py::TestJoinModesScreenerOnly -v`
Expected: FAIL — old `_run_screener_only` uses cascading filter

- [ ] **Step 3: Rewrite `_run_screener_only`**

Replace `_run_screener_only` in `backend/services/backtest/engine.py` (lines 83-94):

```python
    def _run_screener_only(self) -> dict:
        ref_sym = self._all_symbols[0]
        ref_df = self._stock_data[ref_sym]
        last_idx = len(ref_df) - 1
        n_screeners = len(self._screeners)

        per_screener: list[set[str]] = []
        for i, screener in enumerate(self._screeners):
            self._report(i + 1, n_screeners, f"选股中 ({screener.__class__.__name__})")
            ctx = self._make_screener_ctx(screener, last_idx)
            raw_result = screener.screen(ctx, list(self._all_symbols))
            symbols, _ = _parse_screen_result(raw_result)
            per_screener.append(set(symbols))

        merged = per_screener[0] if per_screener else set()
        for pair_idx in range(n_screeners - 1):
            join_mode = self._join_modes[pair_idx]
            next_set = per_screener[pair_idx + 1]
            if join_mode == "independent":
                merged = merged | next_set
                logger.debug("[Screen Pair %d] independent: union=%d", pair_idx, len(merged))
            else:
                merged = merged & next_set
                logger.debug("[Screen Pair %d] correlated: intersection=%d", pair_idx, len(merged))

        return {"screened_symbols": sorted(merged)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_engine.py::TestJoinModesScreenerOnly -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/backtest/engine.py backend/tests/test_engine.py
git commit -m "feat: rewrite _run_screener_only with join_modes support"
```
