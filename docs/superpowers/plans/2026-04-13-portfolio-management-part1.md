# Portfolio Management — Part 1: Backend Service Layer (Tasks 1-3)

Parent plan: `docs/superpowers/plans/2026-04-13-portfolio-management.md`

---

### Task 1: Config + DB Layer

**Files:**
- Modify: `backend/config.py`
- Create: `backend/services/portfolio/__init__.py`
- Create: `backend/services/portfolio/db.py`
- Create: `backend/tests/test_portfolio_db.py`

- [ ] **Step 1: Add PORTFOLIO_DB to config**

In `backend/config.py`, add after line 8 (`LOG_DIR = DATA_DIR / "logs"`):

```python
PORTFOLIO_DB = DATA_DIR / "portfolio.db"
```

- [ ] **Step 2: Create package init**

Create `backend/services/portfolio/__init__.py` as empty file.

- [ ] **Step 3: Write failing tests for db.py**

Create `backend/tests/test_portfolio_db.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_portfolio_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.portfolio'`

- [ ] **Step 5: Implement db.py**

Create `backend/services/portfolio/db.py`:

```python
import sqlite3
from pathlib import Path
from config import PORTFOLIO_DB


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = str(PORTFOLIO_DB)
    conn = sqlite3.Connection(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None):
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            initial_capital REAL NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            commission REAL NOT NULL,
            tax REAL NOT NULL,
            trade_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            cash REAL NOT NULL,
            market_value REAL NOT NULL,
            UNIQUE(portfolio_id, date)
        );
    """)
    conn.commit()

    if close_after:
        conn.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_portfolio_db.py -v`
Expected: All 10 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/services/portfolio/ backend/tests/test_portfolio_db.py
git commit -m "feat(portfolio): add config and SQLite db layer with schema"
```

---

### Task 2: PortfolioManager — CRUD, Trades, Holdings

**Files:**
- Create: `backend/services/portfolio/manager.py`
- Create: `backend/tests/test_portfolio_manager.py`

- [ ] **Step 1: Write failing tests for CRUD + trades + holdings**

Create `backend/tests/test_portfolio_manager.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_portfolio_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.portfolio.manager'`

- [ ] **Step 3: Implement manager.py (CRUD, trades, holdings, summary)**

Create `backend/services/portfolio/manager.py`:

```python
import sqlite3
from datetime import datetime


class PortfolioManager:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_portfolio(self, name: str, initial_capital: float, source: str = "manual") -> dict:
        now = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO portfolios (name, initial_capital, source, created_at) VALUES (?, ?, ?, ?)",
            (name, initial_capital, source, now),
        )
        self._conn.commit()
        return {
            "id": cur.lastrowid,
            "name": name,
            "initial_capital": initial_capital,
            "source": source,
            "created_at": now,
        }

    def delete_portfolio(self, portfolio_id: int):
        self._conn.execute("DELETE FROM portfolios WHERE id=?", (portfolio_id,))
        self._conn.commit()

    def list_portfolios(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM portfolios ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_portfolio(self, portfolio_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def add_trade(
        self,
        portfolio_id: int,
        symbol: str,
        direction: str,
        price: float,
        shares: int,
        trade_date: str,
        commission: float | None = None,
    ) -> dict:
        amount = price * shares
        if commission is None:
            commission = max(amount * 0.0003, 5.0)
        tax = amount * 0.001 if direction == "sell" else 0.0
        now = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO trades (portfolio_id, symbol, direction, price, shares, commission, tax, trade_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (portfolio_id, symbol, direction, price, shares, commission, tax, trade_date, now),
        )
        self._conn.commit()
        return {
            "id": cur.lastrowid,
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "direction": direction,
            "price": price,
            "shares": shares,
            "commission": commission,
            "tax": tax,
            "trade_date": trade_date,
            "created_at": now,
        }

    def get_trades(self, portfolio_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE portfolio_id=? ORDER BY trade_date, id",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_holdings(self, portfolio_id: int) -> dict:
        trades = self.get_trades(portfolio_id)
        holdings: dict[str, dict] = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in holdings:
                holdings[sym] = {"shares": 0, "total_cost": 0.0}
            h = holdings[sym]
            if t["direction"] == "buy":
                old_total = h["total_cost"]
                new_cost = t["price"] * t["shares"]
                h["total_cost"] = old_total + new_cost
                h["shares"] += t["shares"]
            elif t["direction"] == "sell":
                h["shares"] -= t["shares"]
                if h["shares"] > 0:
                    h["total_cost"] = h["total_cost"] * (h["shares"] / (h["shares"] + t["shares"]))
                else:
                    h["total_cost"] = 0.0

        result = {}
        for sym, h in holdings.items():
            if h["shares"] > 0:
                result[sym] = {
                    "shares": h["shares"],
                    "avg_cost": h["total_cost"] / h["shares"],
                }
        return result

    def _compute_cash(self, portfolio_id: int) -> float:
        p = self.get_portfolio(portfolio_id)
        if p is None:
            return 0.0
        cash = p["initial_capital"]
        trades = self.get_trades(portfolio_id)
        for t in trades:
            if t["direction"] == "buy":
                cash -= t["price"] * t["shares"] + t["commission"]
            elif t["direction"] == "sell":
                cash += t["price"] * t["shares"] - t["commission"] - t["tax"]
        return cash

    def compute_summary(self, portfolio_id: int, current_prices: dict[str, float] | None = None) -> dict:
        p = self.get_portfolio(portfolio_id)
        if p is None:
            return {}
        if current_prices is None:
            current_prices = {}
        holdings = self.compute_holdings(portfolio_id)
        cash = self._compute_cash(portfolio_id)
        market_value = sum(
            h["shares"] * current_prices.get(sym, h["avg_cost"])
            for sym, h in holdings.items()
        )
        total_value = cash + market_value
        initial = p["initial_capital"]
        total_return = (total_value - initial) / initial if initial > 0 else 0.0
        return {
            "cash": cash,
            "market_value": market_value,
            "total_value": total_value,
            "total_return": total_return,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_portfolio_manager.py -v`
Expected: All 18 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/portfolio/manager.py backend/tests/test_portfolio_manager.py
git commit -m "feat(portfolio): add PortfolioManager with CRUD, trades, holdings, summary"
```

---

### Task 3: PortfolioManager — Snapshots + Import

**Files:**
- Modify: `backend/services/portfolio/manager.py`
- Modify: `backend/tests/test_portfolio_manager.py`

- [ ] **Step 1: Write failing tests for snapshots and import**

Append to `backend/tests/test_portfolio_manager.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd backend && python -m pytest tests/test_portfolio_manager.py -v -k "Snapshot or Import"`
Expected: FAIL — `AttributeError: 'PortfolioManager' object has no attribute 'take_snapshot'`

- [ ] **Step 3: Add snapshot and import methods to manager.py**

Append these methods to the `PortfolioManager` class in `backend/services/portfolio/manager.py`:

```python
    def take_snapshot(self, portfolio_id: int, date: str, current_prices: dict[str, float]):
        summary = self.compute_summary(portfolio_id, current_prices)
        if not summary:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots (portfolio_id, date, total_value, cash, market_value) VALUES (?, ?, ?, ?, ?)",
            (portfolio_id, date, summary["total_value"], summary["cash"], summary["market_value"]),
        )
        self._conn.commit()

    def take_all_snapshots(self, date: str, current_prices: dict[str, float]):
        portfolios = self.list_portfolios()
        for p in portfolios:
            self.take_snapshot(p["id"], date, current_prices)

    def get_snapshots(self, portfolio_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM snapshots WHERE portfolio_id=? ORDER BY date",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def import_from_backtest(self, backtest_result: dict, name: str) -> dict:
        equity_curve = backtest_result["equity_curve"]
        last_snap = equity_curve[-1]
        total_value = last_snap["total_value"]
        positions = last_snap.get("positions", {})
        cash = last_snap["cash"]
        trade_date = last_snap["date"]

        p = self.create_portfolio(name, total_value, source="backtest")

        for sym, pos in positions.items():
            self.add_trade(
                p["id"],
                sym,
                "buy",
                pos["cost"],
                pos["shares"],
                trade_date,
                commission=0.0,
            )

        return p
```

- [ ] **Step 4: Run all manager tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_portfolio_manager.py -v`
Expected: All 24 tests PASS (18 from Task 2 + 6 new)

- [ ] **Step 5: Commit**

```bash
git add backend/services/portfolio/manager.py backend/tests/test_portfolio_manager.py
git commit -m "feat(portfolio): add snapshots and backtest import to PortfolioManager"
```
