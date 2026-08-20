import sqlite3

import pytest

from services.portfolio.db import init_db
from services.portfolio.holdings_service import get_holdings, record_trade
from services.portfolio.repository import AccountRepository


@pytest.fixture
def portfolio():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    repo = AccountRepository(conn)
    account = repo.create_account("普通账户", "A", "CNY")
    yield conn, repo, account
    conn.close()


def test_unbound_account_accepts_any_buy_and_projects_cost(portfolio):
    conn, _, account = portfolio

    trade = record_trade(account.id, "600519.SH", "buy", 10, 100.0, "2026-08-19", fee=5, connection=conn)
    holdings = get_holdings(account.id, "2026-08-19", connection=conn)

    assert trade.symbol == "600519.SH"
    assert holdings[0].actual_shares == 10
    assert holdings[0].average_cost == pytest.approx(100.5)


def test_bound_account_rejects_non_target_but_allows_any_size_and_price(portfolio):
    conn, repo, account = portfolio
    repo.set_strategy(account.id, "task-1", "2026-08-19")
    repo.add_target_history(account.id, "2026-08-19", '{"task_id":"task-1","targets":[{"symbol":"600519.SH","target_quantity":5,"reference_price":200,"status":"active"}]}', "2026-08-19T00:00:00")
    conn.commit()

    with pytest.raises(ValueError, match="target"):
        record_trade(account.id, "000001.SZ", "buy", 1, 1.0, "2026-08-19", connection=conn)

    record_trade(account.id, "600519.SH", "buy", 50, 1.0, "2026-08-19", connection=conn)
    assert get_holdings(account.id, "2026-08-19", connection=conn)[0].remaining_quantity == 0


def test_bound_account_can_sell_existing_non_target_position(portfolio):
    conn, repo, account = portfolio
    repo.add_trade(account.id, "000001.SZ", "buy", 10, 10, "2026-08-18")
    repo.set_strategy(account.id, "task-1", "2026-08-19")
    repo.add_target_history(account.id, "2026-08-19", '{"task_id":"task-1","targets":[{"symbol":"600519.SH","target_quantity":5,"reference_price":200,"status":"active"}]}', "2026-08-19T00:00:00")
    conn.commit()

    record_trade(account.id, "000001.SZ", "sell", 10, 11, "2026-08-19", connection=conn)
    assert all(holding.symbol != "000001.SZ" for holding in get_holdings(account.id, "2026-08-19", connection=conn))


@pytest.mark.parametrize("field", ["fee", "tax"])
def test_trade_costs_must_be_non_negative(portfolio, field):
    conn, _, account = portfolio

    with pytest.raises(ValueError, match="non-negative"):
        record_trade(account.id, "600519.SH", "buy", 1, 10, "2026-08-19", **{field: -1}, connection=conn)


def test_sell_hides_fully_sold_position_but_preserves_realized_pnl(portfolio):
    conn, _, account = portfolio
    record_trade(account.id, "600519.SH", "buy", 10, 100.0, "2026-08-18", connection=conn)
    record_trade(account.id, "600519.SH", "sell", 10, 110.0, "2026-08-19", tax=1, connection=conn)

    assert get_holdings(account.id, "2026-08-19", connection=conn) == []
    history = AccountRepository(conn).list_trades(account.id)
    assert history[-1]["realized_pnl"] == pytest.approx(99.0)


def test_zero_target_with_actual_shares_is_visible_as_exited(portfolio):
    conn, repo, account = portfolio
    repo.set_strategy(account.id, "task-1", "2026-08-19")
    repo.add_target_history(account.id, "2026-08-18", '{"task_id":"task-1","targets":[{"symbol":"600519.SH","target_quantity":10,"reference_price":200,"status":"active"}]}', "2026-08-18T00:00:00")
    repo.add_target_history(account.id, "2026-08-19", '{"task_id":"task-1","targets":[{"symbol":"600519.SH","target_quantity":0,"reference_price":200,"status":"exited"}]}', "2026-08-19T00:00:00")
    conn.commit()
    record_trade(account.id, "600519.SH", "buy", 10, 100.0, "2026-08-18", connection=conn)

    holding = get_holdings(account.id, "2026-08-19", connection=conn)[0]
    assert holding.target_quantity == 0
    assert holding.target_status == "exited"
    assert holding.remaining_quantity == 0
