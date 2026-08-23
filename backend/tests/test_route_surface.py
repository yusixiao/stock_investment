from main import app


RETAINED_API_PATHS = {
    "/api/health",
    "/api/meta/circulating-shares",
    "/api/meta/circulating-shares/status",
    "/api/meta/circulating-shares/update",
    "/api/meta/duckdb/diag",
    "/api/meta/duckdb/reload",
    "/api/market/hk-connect",
    "/api/market/hk-connect/refresh",
    "/api/market-update/adjust-factor",
    "/api/market-update/progress",
    "/api/market-update/refresh",
    "/api/market-update/trigger",
    "/api/backtest/cache/load",
    "/api/backtest/cache/status",
    "/api/backtest/cache/{market}",
    "/api/backtest/result/{task_id}",
    "/api/backtest/run",
    "/api/backtest/scan-radar",
    "/api/backtest/scan-radar/result/{task_id}",
    "/api/backtest/status/{task_id}",
    "/api/backtest/strategies",
    "/api/backtest/tasks",
    "/api/backtest/tasks/{task_id}",
    "/api/v1/monitoring/center",
    "/api/v1/monitoring/stock-monitors",
    "/api/v1/monitoring/stock-monitors/{monitor_id}",
    "/api/v1/monitoring/stock-monitors/{monitor_id}/events",
    "/api/v1/monitoring/stock-monitors/{monitor_id}/pause",
    "/api/v1/monitoring/stock-monitors/{monitor_id}/resume",
    "/api/v1/monitoring/strategy-monitors",
    "/api/v1/monitoring/strategy-monitors/{monitor_id}",
    "/api/v1/monitoring/strategy-monitors/{monitor_id}/run",
    "/api/v1/monitoring/strategy-monitors/{monitor_id}/runs",
}

REMOVED_ROUTE_PREFIXES = (
    "/api/v1/portfolio",
    "/api/v1/agent",
    "/api/v1/system/config",
    "/api/v1/auth",
    "/api/stocks",
    "/api/screener",
)
REMOVED_EXACT_ROUTES = {
    "/api/stocks/search",
    "/api/market/{code}/kline",
}


def test_backtest_platform_route_surface_whitelists_retained_api_paths():
    api_paths = {route.path for route in app.routes if route.path.startswith("/api/")}

    assert api_paths == RETAINED_API_PATHS


def test_backtest_platform_route_surface_excludes_removed_product_routes():
    api_paths = {route.path for route in app.routes if route.path.startswith("/api/")}

    assert api_paths.isdisjoint(REMOVED_EXACT_ROUTES)
    for prefix in REMOVED_ROUTE_PREFIXES:
        assert not any(path == prefix or path.startswith(prefix + "/") for path in api_paths)
