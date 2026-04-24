### Task 6: 更新现有测试适配行为变更

**Files:**
- Modify: `backend/tests/test_engine.py` (existing tests)
- Modify: `backend/tests/test_strategy_regression.py`

**Prerequisite:** Tasks 2-4 complete

**Background:** 行为变更说明：
- **旧行为**：多 screener 级联过滤 (cascading AND)，match_dates 使用原始日期字符串
- **新行为**：每个 screener 独立运行，默认 `independent` (OR 并集)，match_dates 按频率格式化
- `test_screener_chain` 之前断言只有 1 个结果（AND 级联），现在默认 independent 会返回更多
- `test_mixed_freq_*` 测试断言 match_dates 是月末交易日，现在 match_dates 格式是 `YYYY-MM`(monthly) 或 `YYYY-MM-DD`(daily)

---

- [ ] **Step 1: Update `test_screener_chain`**

The old test asserts `len(result["screened_symbols"]) == 1` because `TopOneScreener` cascades after `AlwaysPassScreener`. With new independent mode (default), both run independently and results are unioned. Since `AlwaysPassScreener` passes all, and `TopOneScreener` passes first one, the union is all symbols.

Replace `test_screener_chain` in `backend/tests/test_engine.py`:

```python
    def test_screener_chain(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener(), TopOneScreener()],
            trader=None,
        )
        result = engine.run()
        assert len(result["screened_symbols"]) == 2
```

- [ ] **Step 2: Update `test_screener_only_mode`**

The old test checked `isinstance(result["screened_symbols"][0], str)`. `_run_screener_only` now returns sorted list of symbols. Update:

```python
    def test_screener_only_mode(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[AlwaysPassScreener()],
            trader=None,
        )
        result = engine.run(mode="screen")
        assert "screened_symbols" in result
        assert isinstance(result["screened_symbols"][0], str)
```

This test should still pass — `_run_screener_only` returns a list of strings.

- [ ] **Step 3: Update `test_mixed_freq_daily_then_monthly_match_dates_are_monthly`**

The old test asserts match_dates are month-end trading dates (raw date strings). With new behavior:
- Each screener runs independently, default `independent` → union results.
- DailyScreener produces daily format (`YYYY-MM-DD`), MonthlyScreener produces monthly format (`YYYY-MM`).
- Pipeline finest freq = daily, so monthly dates (`YYYY-MM`) are **discarded** in final output.
- Only daily dates remain.

Replace the test:

```python
    def test_mixed_freq_daily_then_monthly_match_dates_are_daily_after_union(self):
        class DailyScreener(ScreenerStrategy):
            name = "daily-pass"
            description = ""
            params = {}
            frequency = "daily"
            def screen(self, ctx, symbols):
                return symbols

        class MonthlyScreener(ScreenerStrategy):
            name = "monthly-pass"
            description = ""
            params = {}
            frequency = "monthly"
            def screen(self, ctx, symbols):
                return symbols

        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[DailyScreener(), MonthlyScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        items = result["screened_symbols"]
        assert len(items) > 0
        from services.backtest.date_utils import detect_frequency
        for item in items:
            for d in item["match_dates"]:
                assert detect_frequency(d) == "daily"
```

- [ ] **Step 4: Update `test_mixed_freq_monthly_then_daily_match_dates_are_daily`**

Same logic — independent union, finest = daily, monthly dates discarded. Replace:

```python
    def test_mixed_freq_monthly_then_daily_match_dates_are_daily_after_union(self):
        class DailyScreener(ScreenerStrategy):
            name = "daily-pass"
            description = ""
            params = {}
            frequency = "daily"
            def screen(self, ctx, symbols):
                return symbols

        class MonthlyScreener(ScreenerStrategy):
            name = "monthly-pass"
            description = ""
            params = {}
            frequency = "monthly"
            def screen(self, ctx, symbols):
                return symbols

        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[MonthlyScreener(), DailyScreener()],
            trader=None,
        )
        result = engine.run()
        assert "screened_symbols" in result
        items = result["screened_symbols"]
        assert len(items) > 0
        from services.backtest.date_utils import detect_frequency
        all_dates = set(data[list(data.keys())[0]]["date"].tolist())
        for item in items:
            assert len(item["match_dates"]) > 0
            for d in item["match_dates"]:
                assert detect_frequency(d) == "daily"
                assert d in all_dates
```

- [ ] **Step 5: Update `test_strategy_regression.py`**

The regression tests use `MaTangleBreakoutScreener` (monthly frequency, single screener). With the new engine:
- Single screener: no join_modes needed, behavior unchanged
- match_dates will now be formatted as monthly (`YYYY-MM`) instead of raw date strings like `2025-11-28`

Update `EXPECTED_ALL_MATCH_DATES` in `backend/tests/test_strategy_regression.py`:

```python
EXPECTED_ALL_MATCH_DATES = {
    "000629.SZ": ["2010-11", "2025-11"],
    "301083.SZ": ["2025-07"],
    "002056.SZ": ["2025-06"],
    "002870.SZ": ["2025-06"],
    "300041.SZ": ["2025-06"],
    "300221.SZ": ["2023-09", "2025-01"],
}
```

Also update `EXPECTED_LATEST_MATCH` — the `_screen_single` function tests the strategy directly (not through engine), so its match_dates are raw dates from the strategy. The engine is responsible for formatting. So `_screen_single` results stay as raw dates. **No change needed for `EXPECTED_LATEST_MATCH`.**

Only `_engine_backtest` goes through the engine and will now return monthly-formatted dates. Update `test_engine_all_match_dates`:

```python
@skip_no_data
class TestMaTangleEngineRegression:
    @pytest.mark.parametrize("symbol,expected_dates", list(EXPECTED_ALL_MATCH_DATES.items()))
    def test_engine_all_match_dates(self, symbol, expected_dates):
        result = _engine_backtest([symbol])
        assert symbol in result
        assert result[symbol] == expected_dates
```

- [ ] **Step 6: Run all updated tests**

Run: `python -m pytest backend/tests/test_engine.py -v`
Expected: All PASS

Run: `python -m pytest backend/tests/test_strategy_regression.py -v` (only if data available)
Expected: All PASS (or skipped if no data)

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest backend/tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add backend/tests/test_engine.py backend/tests/test_strategy_regression.py
git commit -m "test: update existing tests for join_modes behavior change"
```
