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

`scripts/smoke_ask_stock.py` still imports `routers.agent`, which was deliberately deleted in this task. The script was left unchanged because Task 3 is limited to backend route registration/deletion and route-surface tests.
