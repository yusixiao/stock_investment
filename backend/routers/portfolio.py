import sqlite3
import pandas as pd
from fastapi import APIRouter, HTTPException, Body

from config import RAW_KLINE_DIR
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


def _get_latest_close(symbol: str) -> float | None:
    """从parquet文件读取最新收盘价。"""
    candidates = list(RAW_KLINE_DIR.glob(f"{symbol}.*.parquet"))
    if not candidates:
        return None
    df = pd.read_parquet(candidates[0], columns=["close"])
    if df.empty:
        return None
    return float(df.iloc[0]["close"])


@router.get("/{portfolio_id}/holdings")
def api_get_holdings(portfolio_id: int):
    mgr = _get_manager()
    holdings = mgr.compute_holdings(portfolio_id)
    result = []
    for sym, h in holdings.items():
        current_price = _get_latest_close(sym) or h["avg_cost"]
        market_value = h["shares"] * current_price
        cost_value = h["shares"] * h["avg_cost"]
        pnl = market_value - cost_value
        pnl_pct = (pnl / cost_value * 100) if cost_value > 0 else 0.0
        result.append({
            "symbol": sym,
            "shares": h["shares"],
            "avg_cost": h["avg_cost"],
            "current_price": current_price,
            "market_value": market_value,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
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
