# Task 3 Report

## Result

Task 3 completed. `backend/main.py` now registers only the retained backtest, backtest cache, metadata, market update, HK-connect, monitoring, and health routes.

Removed router modules:

- `portfolio_v1`
- `agent`
- `system_config`
- `auth_stub`
- `stock`
- `stock_search`
- `market_kline`
- `screener`

Removed or adjusted tests that exclusively exercised deleted routes. Added `backend/tests/test_route_surface.py` covering retained routes and removed product paths.

## Verification

- `python -m pytest backend/tests/test_route_surface.py -q`: passed, 1 test.
- `python -m pytest backend/tests/test_backtest_api.py backend/tests/test_monitoring_api.py -q`: passed, 36 tests.
- `python -m pytest backend/tests/test_strategy_targets.py -q`: passed, 10 tests.
- `python -m pytest backend/tests/ -x -q`: passed, 1519 tests.

The full suite emitted one existing `PytestUnhandledThreadExceptionWarning` from a backtest test using a temporary SQLite database; it did not fail the suite and is unrelated to route registration.

## Concern

The full backend suite emits one existing `PytestUnhandledThreadExceptionWarning` from a backtest test using a temporary SQLite database; it is unrelated to route registration.

## Reviewer Fix

Addressed both valid reviewer findings:

- Strengthened `backend/tests/test_route_surface.py` with an exact retained API whitelist covering health, metadata, HK-connect, market update, backtest/cache, and monitoring endpoints.
- Added an explicit blacklist assertion for all removed portfolio, agent, system-config, auth, stock, stock-search, market-kline, and screener route surfaces.
- Deleted the agent-only `scripts/smoke_ask_stock.py`, removing the stale `routers.agent` import.

## Reviewer-Fix Verification

- `python -m pytest backend/tests/test_route_surface.py -q`: passed, 2 tests.
- `python -m pytest backend/tests/test_route_surface.py backend/tests/test_backtest_api.py backend/tests/test_monitoring_api.py -q`: passed, 38 tests.
- `python -m pytest backend/tests/ -x -q`: passed, 1520 tests.

The warning is caused by a temporary SQLite database without `backtest_tasks`; it is unrelated to this fix.
