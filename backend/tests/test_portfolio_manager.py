import pytest
from services.portfolio.db import get_connection, init_db
from services.portfolio.manager import PortfolioManager


@pytest.fixture
def mgr():
    conn = get_connection(":memory:")
    init_db(conn)
    return PortfolioManager(conn)


class TestCreatePortfolio:
    def test_create(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        assert p["name"] == "test"
        assert p["initial_capital"] == 100000
        assert p["source"] == "manual"
        assert "id" in p

    def test_duplicate_name_raises(self, mgr):
        mgr.create_portfolio("test", 100000)
        with pytest.raises(Exception):
            mgr.create_portfolio("test", 200000)

    def test_create_with_backtest_source(self, mgr):
        p = mgr.create_portfolio("bt", 100000, source="backtest")
        assert p["source"] == "backtest"


class TestDeletePortfolio:
    def test_delete(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.delete_portfolio(p["id"])
        assert mgr.get_portfolio(p["id"]) is None

    def test_delete_nonexistent(self, mgr):
        mgr.delete_portfolio(999)


class TestListPortfolios:
    def test_empty(self, mgr):
        assert mgr.list_portfolios() == []

    def test_list(self, mgr):
        mgr.create_portfolio("a", 100000)
        mgr.create_portfolio("b", 200000)
        result = mgr.list_portfolios()
        assert len(result) == 2


class TestAddTrade:
    def test_buy(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        t = mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 100, "2026-04-10")
        assert t["symbol"] == "600519.SH"
        assert t["direction"] == "buy"
        assert t["shares"] == 100
        assert t["tax"] == 0.0
        assert t["commission"] == max(1800.0 * 100 * 0.0003, 5.0)

    def test_sell_has_tax(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 100.0, 100, "2026-04-10")
        t = mgr.add_trade(p["id"], "600519.SH", "sell", 110.0, 100, "2026-04-11")
        assert t["tax"] == 110.0 * 100 * 0.001
        assert t["commission"] == max(110.0 * 100 * 0.0003, 5.0)

    def test_custom_commission(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        t = mgr.add_trade(p["id"], "600519.SH", "buy", 100.0, 100, "2026-04-10", commission=10.0)
        assert t["commission"] == 10.0

    def test_min_commission_5(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        t = mgr.add_trade(p["id"], "000001.SZ", "buy", 10.0, 100, "2026-04-10")
        assert t["commission"] == 5.0


class TestGetTrades:
    def test_empty(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        assert mgr.get_trades(p["id"]) == []

    def test_returns_trades(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 100, "2026-04-10")
        trades = mgr.get_trades(p["id"])
        assert len(trades) == 1
        assert trades[0]["symbol"] == "600519.SH"


class TestComputeHoldings:
    def test_empty(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        assert mgr.compute_holdings(p["id"]) == {}

    def test_single_buy(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 100, "2026-04-10")
        h = mgr.compute_holdings(p["id"])
        assert "600519.SH" in h
        assert h["600519.SH"]["shares"] == 100
        assert h["600519.SH"]["avg_cost"] == 1800.0

    def test_two_buys_avg_cost(self, mgr):
        p = mgr.create_portfolio("test", 1000000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 100, "2026-04-10")
        mgr.add_trade(p["id"], "600519.SH", "buy", 2000.0, 100, "2026-04-11")
        h = mgr.compute_holdings(p["id"])
        assert h["600519.SH"]["shares"] == 200
        expected_cost = (1800.0 * 100 + 2000.0 * 100) / 200
        assert abs(h["600519.SH"]["avg_cost"] - expected_cost) < 0.01

    def test_buy_then_sell_all(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.add_trade(p["id"], "000001.SZ", "buy", 10.0, 100, "2026-04-10")
        mgr.add_trade(p["id"], "000001.SZ", "sell", 12.0, 100, "2026-04-11")
        h = mgr.compute_holdings(p["id"])
        assert "000001.SZ" not in h

    def test_partial_sell(self, mgr):
        p = mgr.create_portfolio("test", 1000000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 200, "2026-04-10")
        mgr.add_trade(p["id"], "600519.SH", "sell", 2000.0, 100, "2026-04-11")
        h = mgr.compute_holdings(p["id"])
        assert h["600519.SH"]["shares"] == 100
        assert h["600519.SH"]["avg_cost"] == 1800.0


class TestComputeSummary:
    def test_empty_portfolio(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        s = mgr.compute_summary(p["id"])
        assert s["cash"] == 100000
        assert s["market_value"] == 0
        assert s["total_value"] == 100000
        assert s["total_return"] == 0.0

    def test_with_holdings(self, mgr):
        p = mgr.create_portfolio("test", 200000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 100, "2026-04-10")
        commission = max(1800.0 * 100 * 0.0003, 5.0)
        s = mgr.compute_summary(p["id"], current_prices={"600519.SH": 1900.0})
        assert s["cash"] == pytest.approx(200000 - 1800.0 * 100 - commission)
        assert s["market_value"] == pytest.approx(1900.0 * 100)
        expected_total = s["cash"] + s["market_value"]
        assert s["total_value"] == pytest.approx(expected_total)
        assert s["total_return"] == pytest.approx((expected_total - 200000) / 200000)


class TestTakeSnapshot:
    def test_snapshot(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.add_trade(p["id"], "600519.SH", "buy", 1800.0, 100, "2026-04-10")
        mgr.take_snapshot(p["id"], "2026-04-10", {"600519.SH": 1850.0})
        snaps = mgr.get_snapshots(p["id"])
        assert len(snaps) == 1
        assert snaps[0]["date"] == "2026-04-10"
        assert snaps[0]["total_value"] > 0

    def test_snapshot_upsert(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.take_snapshot(p["id"], "2026-04-10", {})
        mgr.take_snapshot(p["id"], "2026-04-10", {})
        snaps = mgr.get_snapshots(p["id"])
        assert len(snaps) == 1

    def test_get_snapshots_ordered(self, mgr):
        p = mgr.create_portfolio("test", 100000)
        mgr.take_snapshot(p["id"], "2026-04-12", {})
        mgr.take_snapshot(p["id"], "2026-04-10", {})
        mgr.take_snapshot(p["id"], "2026-04-11", {})
        snaps = mgr.get_snapshots(p["id"])
        dates = [s["date"] for s in snaps]
        assert dates == ["2026-04-10", "2026-04-11", "2026-04-12"]


class TestTakeAllSnapshots:
    def test_snapshots_all(self, mgr):
        mgr.create_portfolio("a", 100000)
        mgr.create_portfolio("b", 200000)
        mgr.take_all_snapshots("2026-04-10", {})
        snaps_a = mgr.get_snapshots(1)
        snaps_b = mgr.get_snapshots(2)
        assert len(snaps_a) == 1
        assert len(snaps_b) == 1


class TestImportFromBacktest:
    def test_import(self, mgr):
        backtest_result = {
            "equity_curve": [
                {"date": "2026-04-09", "total_value": 1000000, "cash": 900000, "market_value": 100000, "positions": {"600519.SH": {"shares": 100, "cost": 1000.0, "market_price": 1000.0}}},
                {"date": "2026-04-10", "total_value": 1050000, "cash": 900000, "market_value": 150000, "positions": {"600519.SH": {"shares": 100, "cost": 1000.0, "market_price": 1500.0}}},
            ],
            "trades": [],
        }
        p = mgr.import_from_backtest(backtest_result, "imported")
        assert p["source"] == "backtest"
        assert p["initial_capital"] == 1050000
        holdings = mgr.compute_holdings(p["id"])
        assert holdings["600519.SH"]["shares"] == 100
        assert holdings["600519.SH"]["avg_cost"] == 1000.0

    def test_import_empty_positions(self, mgr):
        backtest_result = {
            "equity_curve": [
                {"date": "2026-04-10", "total_value": 1000000, "cash": 1000000, "market_value": 0, "positions": {}},
            ],
            "trades": [],
        }
        p = mgr.import_from_backtest(backtest_result, "empty")
        assert p["initial_capital"] == 1000000
        assert mgr.compute_holdings(p["id"]) == {}
