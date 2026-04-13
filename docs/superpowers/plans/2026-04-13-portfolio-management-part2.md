# Portfolio Management — Part 2: Backend API + Integration (Tasks 4-5)

Parent plan: `docs/superpowers/plans/2026-04-13-portfolio-management.md`

---

### Task 4: Portfolio API Router

**Files:**
- Create: `backend/routers/portfolio.py`
- Create: `backend/tests/test_portfolio_api.py`

- [ ] **Step 1: Write failing tests for API endpoints**

Create `backend/tests/test_portfolio_api.py`:

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from services.portfolio.db import get_connection, init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_db():
    conn = get_connection(":memory:")
    init_db(conn)
    with patch("routers.portfolio._get_manager") as mock:
        from services.portfolio.manager import PortfolioManager
        mgr = PortfolioManager(conn)
        mock.return_value = mgr
        yield mgr
    conn.close()


class TestCreatePortfolio:
    def test_create(self):
        resp = client.post("/api/portfolio/", json={"name": "test", "initial_capital": 100000})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test"
        assert data["initial_capital"] == 100000
        assert data["source"] == "manual"

    def test_duplicate_returns_400(self):
        client.post("/api/portfolio/", json={"name": "dup", "initial_capital": 100000})
        resp = client.post("/api/portfolio/", json={"name": "dup", "initial_capital": 100000})
        assert resp.status_code == 400


class TestListPortfolios:
    def test_list_empty(self):
        resp = client.get("/api/portfolio/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self):
        client.post("/api/portfolio/", json={"name": "a", "initial_capital": 100000})
        resp = client.get("/api/portfolio/")
        assert len(resp.json()) == 1


class TestGetPortfolio:
    def test_get(self):
        create = client.post("/api/portfolio/", json={"name": "t", "initial_capital": 100000}).json()
        resp = client.get(f"/api/portfolio/{create['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "t"

    def test_404(self):
        resp = client.get("/api/portfolio/999")
        assert resp.status_code == 404


class TestDeletePortfolio:
    def test_delete(self):
        create = client.post("/api/portfolio/", json={"name": "del", "initial_capital": 100000}).json()
        resp = client.delete(f"/api/portfolio/{create['id']}")
        assert resp.status_code == 200
        resp2 = client.get(f"/api/portfolio/{create['id']}")
        assert resp2.status_code == 404


class TestTrades:
    def test_add_trade(self):
        p = client.post("/api/portfolio/", json={"name": "tr", "initial_capital": 100000}).json()
        resp = client.post(f"/api/portfolio/{p['id']}/trades", json={
            "symbol": "600519.SH", "direction": "buy", "price": 1800.0, "shares": 100, "trade_date": "2026-04-10"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "600519.SH"
        assert data["commission"] > 0

    def test_get_trades(self):
        p = client.post("/api/portfolio/", json={"name": "tr2", "initial_capital": 100000}).json()
        client.post(f"/api/portfolio/{p['id']}/trades", json={
            "symbol": "600519.SH", "direction": "buy", "price": 1800.0, "shares": 100, "trade_date": "2026-04-10"
        })
        resp = client.get(f"/api/portfolio/{p['id']}/trades")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestHoldings:
    def test_holdings(self):
        p = client.post("/api/portfolio/", json={"name": "h", "initial_capital": 200000}).json()
        client.post(f"/api/portfolio/{p['id']}/trades", json={
            "symbol": "600519.SH", "direction": "buy", "price": 1800.0, "shares": 100, "trade_date": "2026-04-10"
        })
        resp = client.get(f"/api/portfolio/{p['id']}/holdings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "600519.SH"
        assert data[0]["shares"] == 100


class TestSnapshots:
    def test_snapshots_empty(self):
        p = client.post("/api/portfolio/", json={"name": "sn", "initial_capital": 100000}).json()
        resp = client.get(f"/api/portfolio/{p['id']}/snapshots")
        assert resp.status_code == 200
        assert resp.json() == []


class TestImport:
    def test_import_nonexistent_task(self):
        resp = client.post("/api/portfolio/import/nonexistent", json={"name": "imp"})
        assert resp.status_code == 404

    @patch("routers.portfolio.task_manager")
    def test_import_success(self, mock_tm):
        mock_tm.get_result.return_value = {
            "task_id": "abc123",
            "status": "success",
            "result": {
                "equity_curve": [
                    {"date": "2026-04-10", "total_value": 1050000, "cash": 900000, "market_value": 150000, "positions": {"600519.SH": {"shares": 100, "cost": 1000.0, "market_price": 1500.0}}},
                ],
                "trades": [],
            },
            "error": None,
        }
        resp = client.post("/api/portfolio/import/abc123", json={"name": "imported"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "backtest"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_portfolio_api.py -v`
Expected: FAIL — `ModuleNotFoundError` or import error since router doesn't exist yet

- [ ] **Step 3: Implement portfolio router**

Create `backend/routers/portfolio.py`:

```python
import sqlite3
from fastapi import APIRouter, HTTPException, Body

from services.portfolio.db import get_connection, init_db
from services.portfolio.manager import PortfolioManager
from services.backtest.task_manager import task_manager

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _get_manager() -> PortfolioManager:
    conn = get_connection()
    init_db(conn)
    return PortfolioManager(conn)


@router.post("/")
def api_create_portfolio(body: dict = Body(...)):
    mgr = _get_manager()
    try:
        return mgr.create_portfolio(body["name"], body["initial_capital"])
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Portfolio name already exists")


@router.get("/")
def api_list_portfolios():
    mgr = _get_manager()
    return mgr.list_portfolios()


@router.get("/{portfolio_id}")
def api_get_portfolio(portfolio_id: int):
    mgr = _get_manager()
    p = mgr.get_portfolio(portfolio_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    summary = mgr.compute_summary(portfolio_id)
    return {**p, **summary}


@router.delete("/{portfolio_id}")
def api_delete_portfolio(portfolio_id: int):
    mgr = _get_manager()
    mgr.delete_portfolio(portfolio_id)
    return {"ok": True}


@router.post("/{portfolio_id}/trades")
def api_add_trade(portfolio_id: int, body: dict = Body(...)):
    mgr = _get_manager()
    p = mgr.get_portfolio(portfolio_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return mgr.add_trade(
        portfolio_id,
        body["symbol"],
        body["direction"],
        body["price"],
        body["shares"],
        body["trade_date"],
        commission=body.get("commission"),
    )


@router.get("/{portfolio_id}/trades")
def api_get_trades(portfolio_id: int):
    mgr = _get_manager()
    return mgr.get_trades(portfolio_id)


@router.get("/{portfolio_id}/holdings")
def api_get_holdings(portfolio_id: int):
    mgr = _get_manager()
    holdings = mgr.compute_holdings(portfolio_id)
    result = []
    for sym, h in holdings.items():
        result.append({
            "symbol": sym,
            "shares": h["shares"],
            "avg_cost": h["avg_cost"],
            "current_price": h["avg_cost"],
            "market_value": h["shares"] * h["avg_cost"],
            "pnl": 0.0,
            "pnl_pct": 0.0,
        })
    return result


@router.get("/{portfolio_id}/snapshots")
def api_get_snapshots(portfolio_id: int):
    mgr = _get_manager()
    return mgr.get_snapshots(portfolio_id)


@router.post("/import/{task_id}")
def api_import_from_backtest(task_id: str, body: dict = Body(...)):
    result = task_manager.get_result(task_id)
    if result is None or result.get("status") != "success":
        raise HTTPException(status_code=404, detail="Backtest result not found or not successful")
    mgr = _get_manager()
    try:
        return mgr.import_from_backtest(result["result"], body["name"])
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Portfolio name already exists")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_portfolio_api.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/portfolio.py backend/tests/test_portfolio_api.py
git commit -m "feat(portfolio): add REST API router with all endpoints"
```

---

### Task 5: Integration (main.py, scheduler.py)

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/scheduler.py`

- [ ] **Step 1: Register portfolio router in main.py**

In `backend/main.py`, add import after line 8:

```python
from routers.portfolio import router as portfolio_router
```

Add after line 12 (`async def lifespan(app: FastAPI):`), inside the lifespan before `start_scheduler()`:

```python
    from services.portfolio.db import init_db
    init_db()
```

Add after line 32 (`app.include_router(screener_router)`):

```python
app.include_router(portfolio_router)
```

The full `backend/main.py` should become:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.stock import router as stock_router
from routers.data_update import router as data_update_router
from routers.backtest import router as backtest_router
from routers.screener import router as screener_router
from routers.portfolio import router as portfolio_router
from scheduler import start_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.portfolio.db import init_db
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Stock Investment Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stock_router)
app.include_router(data_update_router)
app.include_router(backtest_router)
app.include_router(screener_router)
app.include_router(portfolio_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
```

- [ ] **Step 2: Add snapshot job to scheduler.py**

Replace `backend/scheduler.py` with:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULER_HOUR, SCHEDULER_MINUTE

scheduler = BackgroundScheduler()


def _snapshot_job():
    import pandas as pd
    from config import QFQ_KLINE_DIR
    from services.portfolio.db import get_connection, init_db
    from services.portfolio.manager import PortfolioManager

    current_prices = {}
    latest_date = ""
    for filepath in QFQ_KLINE_DIR.glob("*.parquet"):
        symbol = filepath.stem
        df = pd.read_parquet(filepath, columns=["date", "close"])
        if not df.empty:
            current_prices[symbol] = float(df.iloc[0]["close"])
            d = df.iloc[0]["date"]
            if d > latest_date:
                latest_date = d

    if not latest_date:
        return

    conn = get_connection()
    init_db(conn)
    mgr = PortfolioManager(conn)
    mgr.take_all_snapshots(latest_date, current_prices)
    conn.close()


def start_scheduler():
    from routers.data_update import run_update_task
    scheduler.add_job(
        run_update_task,
        "cron",
        args=["scheduled"],
        day_of_week="mon-fri",
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE,
        id="daily_update",
        replace_existing=True,
    )
    scheduler.add_job(
        _snapshot_job,
        "cron",
        day_of_week="mon-fri",
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE + 10,
        id="daily_snapshot",
        replace_existing=True,
    )
    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown(wait=False)
```

- [ ] **Step 3: Run all existing tests to verify nothing is broken**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS (110 existing + 34 new = 144 total)

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/scheduler.py
git commit -m "feat(portfolio): integrate router and daily snapshot scheduler"
```
