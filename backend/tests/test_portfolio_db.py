import sqlite3
import pytest
from services.portfolio.db import get_connection, init_db


class TestGetConnection:
    def test_returns_connection(self):
        conn = get_connection(":memory:")
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode(self):
        conn = get_connection(":memory:")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal" or mode == "memory"
        conn.close()

    def test_foreign_keys_enabled(self):
        conn = get_connection(":memory:")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        conn.close()

    def test_row_factory(self):
        conn = get_connection(":memory:")
        assert conn.row_factory == sqlite3.Row
        conn.close()


class TestInitDb:
    def test_creates_tables(self):
        conn = get_connection(":memory:")
        init_db(conn)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "portfolios" in tables
        assert "trades" in tables
        assert "snapshots" in tables
        conn.close()

    def test_idempotent(self):
        conn = get_connection(":memory:")
        init_db(conn)
        init_db(conn)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "portfolios" in tables
        conn.close()

    def test_portfolios_schema(self):
        conn = get_connection(":memory:")
        init_db(conn)
        conn.execute("INSERT INTO portfolios (name, initial_capital, source, created_at) VALUES ('test', 100000, 'manual', '2026-01-01T00:00:00')")
        row = conn.execute("SELECT * FROM portfolios WHERE name='test'").fetchone()
        assert row["name"] == "test"
        assert row["initial_capital"] == 100000
        assert row["source"] == "manual"
        conn.close()

    def test_trades_foreign_key(self):
        conn = get_connection(":memory:")
        init_db(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO trades (portfolio_id, symbol, direction, price, shares, commission, tax, trade_date, created_at) VALUES (999, '600519.SH', 'buy', 1800, 100, 5.0, 0, '2026-01-01', '2026-01-01T00:00:00')")
        conn.close()

    def test_snapshots_unique_constraint(self):
        conn = get_connection(":memory:")
        init_db(conn)
        conn.execute("INSERT INTO portfolios (name, initial_capital, source, created_at) VALUES ('test', 100000, 'manual', '2026-01-01T00:00:00')")
        pid = conn.execute("SELECT id FROM portfolios WHERE name='test'").fetchone()["id"]
        conn.execute("INSERT INTO snapshots (portfolio_id, date, total_value, cash, market_value) VALUES (?, '2026-01-01', 100000, 100000, 0)", (pid,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO snapshots (portfolio_id, date, total_value, cash, market_value) VALUES (?, '2026-01-01', 100000, 100000, 0)", (pid,))
        conn.close()

    def test_cascade_delete(self):
        conn = get_connection(":memory:")
        init_db(conn)
        conn.execute("INSERT INTO portfolios (name, initial_capital, source, created_at) VALUES ('test', 100000, 'manual', '2026-01-01T00:00:00')")
        pid = conn.execute("SELECT id FROM portfolios WHERE name='test'").fetchone()["id"]
        conn.execute("INSERT INTO trades (portfolio_id, symbol, direction, price, shares, commission, tax, trade_date, created_at) VALUES (?, '600519.SH', 'buy', 1800, 100, 5.0, 0, '2026-01-01', '2026-01-01T00:00:00')", (pid,))
        conn.execute("INSERT INTO snapshots (portfolio_id, date, total_value, cash, market_value) VALUES (?, '2026-01-01', 100000, 100000, 0)", (pid,))
        conn.execute("DELETE FROM portfolios WHERE id=?", (pid,))
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
        conn.close()
