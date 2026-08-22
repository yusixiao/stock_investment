from main import app


def test_backtest_platform_route_surface():
    paths = {route.path for route in app.routes}

    assert "/api/backtest/run" in paths
    assert "/api/backtest/scan-radar" in paths
    assert "/api/backtest/cache/status" in paths
    assert "/api/v1/monitoring/strategy-monitors" in paths
    assert "/api/market-update/trigger" in paths
    assert "/api/v1/portfolio/accounts" not in paths
    assert "/api/v1/agent/chat/stream" not in paths
    assert "/api/v1/system/config" not in paths
    assert "/api/v1/auth/status" not in paths
    assert "/api/stocks/{symbol}/kline" not in paths
