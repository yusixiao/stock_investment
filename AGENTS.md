# AGENTS.md

## Goal

Build a personal A-share stock investment comprehensive platform (综合平台) with Web UI. The project is built incrementally as sub-projects. Sub-projects 1 (Data Management + K-line Visualization), 2 (Screener + Backtest System), and 3 (Portfolio Management) are complete. Currently enhancing the backtest engine with multi-frequency strategy support, progress reporting, and task persistence.

## Instructions

- **Language**: Communicate in Chinese (中文)
- **Tech stack**: Python full-stack — FastAPI backend, Vue 3 + ECharts frontend
- **Data source**: AKShare (`stock_zh_a_spot_em` for batch daily updates)
- **Data storage**: Parquet files per stock — `data/kline/A/raw/` (不复权) and `data/kline/A/qfq/` (前复权)
- **No code comments**: The user explicitly requires no code comments in any files
- **MACD bar**: `2 × (DIF - DEA)` per user's explicit request
- **Strategy definition**: Python code in local `.py` files, loaded via importlib (trust local user)
- **Architecture**: Event-driven backtest engine with Broker (T+1, 涨跌停, commission万三+印花税千一, slippage)
- **Pipeline model**: 0..N ScreenerStrategy → 0..1 TraderStrategy. Pipeline order is user-defined (not auto-sorted by frequency).
- **Trade price**: `(open + close) / 2` mid-price by default
- **Data**: Backtest uses `qfq/` data; K-line display supports toggle between `raw` and `qfq`
- **年化收益率 formula**: `(1 + total_return) ^ (1 / years) - 1` where `years = natural_days / 365.25`
- **Portfolio management persistence**: SQLite (`data/portfolio.db`) — tables: portfolios, trades, snapshots, backtest_tasks
- **Holdings computed in memory** from trade records, not persisted separately
- **Valuation**: Use parquet latest close price (not real-time API)
- **AKShare API calls timeout in this environment** — all API-calling code must be tested with mocks
- **The `write` tool can abort on large content** — workaround is splitting into multiple smaller writes
- **Frontend port**: 3001 in `vite.config.js`
- **Strategy frequency**: Each ScreenerStrategy declares `frequency = "daily" | "weekly" | "monthly"`. Engine precomputes weekly/monthly K-line caches at startup. Context auto-selects data by frequency.
- **Mixed-frequency pipeline**: Iterate at daily granularity. Each screener only re-executes when its own frequency period changes; otherwise cached result is reused. Match dates only recorded when at least one screener actually executed (`any_executed` flag).
- **Pipeline order**: Maintained as user defines in UI — NOT auto-sorted by frequency.

## Discoveries

- `data/kline/A/raw/` contains **不复权** (unadjusted) price data; `data/kline/A/qfq/` contains **前复权** (forward-adjusted) data.
- Parquet files: 7 columns (date string, open/high/low/close/volume/amount float64), descending date order.
- The engine has three execution paths:
  - `run(mode="screen")` — **选股模式**: only evaluates at the latest bar, returns `{"screened_symbols": ["sym1", ...]}`. Used by `/api/screener/run`.
  - `run()` with `trader=None` — **选股回测模式**: iterates all historical bars with period-based caching, returns `{"screened_symbols": [{"symbol": "sym1", "match_dates": ["2024-01-15", ...]}, ...]}`. Used by `/api/backtest/run` when no Trader strategy is selected.
  - `run()` with trader — **完整回测模式**: iterates all bars with screener + trader, returns metrics/equity_curve/trades.
- Task results are now persisted to SQLite `backtest_tasks` table in `portfolio.db`. Progress tracking remains in-memory.
- **Critical performance issue found and solved**: Monthly strategies were causing N_days × N_stocks × monthly_aggregation computations. Fixed by: (1) engine precomputes weekly/monthly K-line caches at startup, (2) ScreenerContext auto-selects data by frequency, (3) period-based caching in backtest loop skips re-execution when period hasn't changed.
- **Match date duplication bug**: When a monthly strategy's cached result was reused daily, match dates were recorded every day. Fix: only record matches when `any_executed` is True (at least one screener ran fresh).
- `aggregate_kline()` in `services/stock_data.py` handles weekly (W-FRI) and monthly (M) aggregation.

## Accomplished

### Sub-projects 1-3: Complete

### Enhancements completed:

1. **Backtest progress reporting**: TaskManager tracks `progress` (current/total/phase). Engine reports progress via `on_progress` callback. BacktestPage shows progress bar with phase text and percentage. Router reports "加载数据中..." and "数据加载完成" phases.

2. **Multi-frequency strategy support**:
   - `ScreenerStrategy.frequency` attribute (`daily`/`weekly`/`monthly`, default `daily`)
   - Engine precomputes weekly/monthly K-line caches at startup via `aggregate_kline()`
   - `ScreenerContext` accepts multi-period data, `get_history()`/`get_price()`/`indicator()` auto-select by frequency
   - Strategy loader returns `frequency` in scan results
   - Frontend PipelineBuilder shows frequency badges (日线/周线/月线 with colors)

3. **Period-based caching in backtest loop**: Each screener only re-executes when its period key changes. Cached results reused between period changes. Both `_run_screener_backtest` and `_run_backtest` use this.

4. **Match date deduplication fix**: `any_executed` flag ensures matches only recorded when at least one screener freshly executed (not just reusing cache).

5. **Task persistence to SQLite**: `backtest_tasks` table with columns: task_id, status, task_type, pipeline_info, start_date, end_date, summary, result, error, created_at. TaskManager reads/writes SQLite instead of in-memory dict. Progress remains in-memory.

6. **Task history list in BacktestPage**: Shows all historical tasks with type badge (选股/回测), status, summary (选出N只 / 收益X%/回撤Y%), created_at, and "查看结果" button.

7. **Pipeline info in result detail page**: BacktestResult.vue shows strategy config section with name, type badge, frequency badge, and actual parameter values.

8. **Backtest date range**: Stored in task, displayed in result detail page.

9. **Data update date picker**: UpdateStatus.vue has date input (defaults to today), passed to backend API.

10. **Frontend poll error handling**: pollStatus catches errors and stops polling gracefully.

11. **Updated ma_tangle_breakout_screener**: Uses `frequency = "monthly"`, removed internal `_monthly_ma` aggregation (ctx.get_history() now returns monthly data directly).

## Relevant files / directories

```
stock_investment/
├── backend/
│   ├── main.py                         # FastAPI app, lifespan with init_db + scheduler
│   ├── config.py                       # PORTFOLIO_DB, UPDATE_PROGRESS_FILE, etc.
│   ├── scheduler.py                    # Daily snapshot cron
│   ├── routers/
│   │   ├── stock.py
│   │   ├── data_update.py              # POST accepts optional {date} body
│   │   ├── backtest.py                 # Builds pipeline_info, passes task_type/start_date/end_date to TaskManager
│   │   ├── screener.py
│   │   └── portfolio.py
│   ├── services/
│   │   ├── stock_data.py               # aggregate_kline() for weekly/monthly
│   │   ├── indicator.py
│   │   ├── data_updater.py
│   │   ├── backtest/
│   │   │   ├── engine.py               # Precomputes period caches, _period_key(), period-based caching, any_executed flag
│   │   │   ├── base.py                 # ScreenerStrategy.frequency = "daily"
│   │   │   ├── context.py              # Multi-period ScreenerContext with _get_data_for_freq()
│   │   │   ├── broker.py
│   │   │   ├── portfolio.py
│   │   │   ├── analyzer.py
│   │   │   ├── strategy_loader.py      # Returns frequency in scan results
│   │   │   └── task_manager.py         # SQLite-backed, pipeline_info/start_date/end_date/summary columns
│   │   └── portfolio/
│   │       ├── db.py
│   │       └── manager.py
│   └── tests/
│       ├── test_engine.py
│       ├── test_ma_tangle_screener.py
│       ├── test_portfolio_db.py
│       ├── test_portfolio_manager.py
│       ├── test_portfolio_api.py
│       └── ... (168 tests total, all passing)
├── strategies/examples/
│   ├── ma_cross_screener.py            # frequency defaults to "daily"
│   ├── macd_screener.py                # frequency defaults to "daily"
│   ├── equal_weight_trader.py
│   └── ma_tangle_breakout_screener.py  # frequency = "monthly"
├── frontend/
│   ├── vite.config.js                  # port 3001
│   ├── src/
│   │   ├── App.vue
│   │   ├── router/index.js
│   │   ├── api/index.js                # triggerUpdate(date), fetchBacktestTasks, etc.
│   │   ├── views/
│   │   │   ├── BacktestPage.vue        # Progress bar, task history table with type/summary
│   │   │   ├── BacktestResult.vue      # Pipeline info section with params, date range display
│   │   │   ├── ScreenerPage.vue
│   │   │   ├── StockList.vue
│   │   │   ├── PortfolioList.vue
│   │   │   ├── PortfolioDetail.vue
│   │   │   └── ComparePage.vue
│   │   └── components/
│   │       ├── PipelineBuilder.vue     # Frequency badges (日线/周线/月线)
│   │       ├── UpdateStatus.vue        # Date picker for data update
│   │       ├── ParamEditor.vue
│   │       ├── TradeForm.vue
│   │       ├── PortfolioEquity.vue
│   │       └── ... (other components)
├── data/
│   ├── kline/A/raw/                    # ~5212 parquet files
│   ├── kline/A/qfq/                    # ~5208 parquet files
│   ├── portfolio.db                    # SQLite: portfolios, trades, snapshots, backtest_tasks
│   └── logs/
└── .gitignore                          # data/, .superpowers/
```

## Testing

```bash
python -m pytest backend/tests/ -x -q
```

168 tests, all passing.
