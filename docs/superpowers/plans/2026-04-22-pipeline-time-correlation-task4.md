### Task 4: 重写 `_run_backtest` — 独立运行 + 逐对合并 + trader 集成

**Files:**
- Modify: `backend/services/backtest/engine.py:174-256` (`_run_backtest`)
- Modify: `backend/tests/test_engine.py`

**Prerequisite:** Task 2 complete (helper methods exist), Task 3 complete

---

- [ ] **Step 1: Write failing tests for join_modes in full backtest mode**

Append to `backend/tests/test_engine.py`:

```python
class TestJoinModesFullBacktest:
    def _make_data(self):
        return {
            "AAA.SH": _make_stock_df(100, seed=42, base_price=50.0),
            "BBB.SZ": _make_stock_df(100, seed=43, base_price=100.0),
            "CCC.SZ": _make_stock_df(100, seed=44, base_price=80.0),
            "DDD.SH": _make_stock_df(100, seed=45, base_price=60.0),
        }

    def test_independent_backtest_has_more_trades(self):
        data = self._make_data()
        engine_ind = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=BuyAndHoldTrader(),
            join_modes=["independent"],
        )
        result_ind = engine_ind.run()
        assert "metrics" in result_ind
        assert "trades" in result_ind
        assert len(result_ind["trades"]) > 0

    def test_correlated_no_overlap_no_trades(self):
        data = self._make_data()
        engine_cor = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=BuyAndHoldTrader(),
            join_modes=["correlated"],
        )
        result_cor = engine_cor.run()
        assert "metrics" in result_cor
        assert result_cor["trades"] == []

    def test_default_independent_backtest(self):
        data = self._make_data()
        engine = BacktestEngine(
            stock_data=data,
            screeners=[FirstHalfScreener(), SecondHalfScreener()],
            trader=BuyAndHoldTrader(),
        )
        result = engine.run()
        assert len(result["trades"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_engine.py::TestJoinModesFullBacktest -v`
Expected: FAIL — old `_run_backtest` uses cascading filter

- [ ] **Step 3: Rewrite `_run_backtest`**

Replace `_run_backtest` in `backend/services/backtest/engine.py`:

```python
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
        n_screeners = len(self._screeners)

        equity_curve = []
        days_since_rebalance = 0
        prev_closes: dict[str, float] = {}
        bt_screener_cache: dict[int, list[str]] = {}
        bt_prev_keys: dict[int, str] = {}

        for idx in range(n_bars):
            if idx % 10 == 0 or idx == n_bars - 1:
                self._report(idx + 1, n_bars, "回测中")
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
            current_date = ref_df.iloc[idx]["date"]

            per_screener: list[set[str]] = []
            for si, screener in enumerate(self._screeners):
                freq = getattr(screener, "frequency", "daily")
                pk = self._period_key(current_date, freq)
                need_run = (si not in bt_prev_keys) or (pk != bt_prev_keys[si])
                if need_run:
                    ctx = self._make_screener_ctx(screener, idx)
                    raw_result = screener.screen(ctx, list(available_symbols))
                    syms, _ = _parse_screen_result(raw_result)
                    bt_screener_cache[si] = list(syms)
                    bt_prev_keys[si] = pk
                per_screener.append(set(bt_screener_cache.get(si, [])))

            merged = per_screener[0] if per_screener else set()
            for pair_idx in range(n_screeners - 1):
                join_mode = self._join_modes[pair_idx]
                next_set = per_screener[pair_idx + 1]
                if join_mode == "independent":
                    merged = merged | next_set
                else:
                    merged = merged & next_set

            symbols = [s for s in available_symbols if s in merged]

            trader_ctx = TraderContext(
                stock_data=self._stock_data,
                current_idx=idx,
                portfolio=broker.portfolio,
                broker_submit=broker.submit_order,
                selected_symbols=symbols,
                days_since_rebalance=days_since_rebalance,
                weekly_data=self._weekly_data,
                monthly_data=self._monthly_data,
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

Run: `python -m pytest backend/tests/test_engine.py::TestJoinModesFullBacktest -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run all engine tests**

Run: `python -m pytest backend/tests/test_engine.py -v`
Expected: New tests PASS. Some existing tests may need updates (Task 6).

- [ ] **Step 6: Commit**

```bash
git add backend/services/backtest/engine.py backend/tests/test_engine.py
git commit -m "feat: rewrite _run_backtest with join_modes support"
```
