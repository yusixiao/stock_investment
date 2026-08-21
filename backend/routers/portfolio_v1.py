from dataclasses import asdict
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.backtest.task_manager import task_manager
from services.market_data.duckdb_store import get_store
from services.portfolio.account_service import (
    AccountService,
    TargetMaterializerUnavailable,
)
from services.portfolio.strategy_targets import materialize_targets
from services.portfolio.db import get_connection, init_db
from services.portfolio.holdings_service import build_snapshot, delete_trade as delete_trade_service, get_holdings, record_trade
from services.portfolio.repository import AccountRepository

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio-v1"])


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    market: str = Field(min_length=1)
    base_currency: str = Field(min_length=1)
    strategy_task_id: str | None = None


class StrategyBindingRequest(BaseModel):
    task_id: str = Field(min_length=1)


class TradeCreateRequest(BaseModel):
    account_id: int
    symbol: str = Field(min_length=1)
    side: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: str
    fee: float = Field(default=0, ge=0)
    tax: float = Field(default=0, ge=0)


def _get_connection():
    conn = get_connection()
    try:
        init_db(conn)
        return conn
    except Exception:
        conn.close()
        raise


def _close_connection(conn):
    conn.close()


@contextmanager
def _connection_scope():
    conn = _get_connection()
    try:
        yield conn
    finally:
        _close_connection(conn)


def _get_task_manager():
    return task_manager


def _get_materializer():
    return materialize_targets


def _get_store():
    return get_store()


def _normalize_market(market: str) -> str:
    normalized = market.upper()
    aliases = {"CN": "A", "A": "A", "HK": "HK", "US": "US"}
    if normalized not in aliases:
        raise ValueError("unsupported market")
    return aliases[normalized]


def _get_service(connection) -> AccountService:
    conn = connection
    return AccountService(
        AccountRepository(conn),
        _get_task_manager(),
        target_materializer=_get_materializer(),
    )


def _error(exc: ValueError):
    status = 404 if str(exc) == "account not found" else 409
    raise HTTPException(status_code=status, detail=str(exc))


def _materializer_error(exc: TargetMaterializerUnavailable):
    raise HTTPException(status_code=503, detail=str(exc))


def _not_implemented():
    raise HTTPException(status_code=501, detail="portfolio capability is not implemented")


@router.post("/accounts", status_code=201)
def create_account(body: AccountCreateRequest):
    try:
        with _connection_scope() as conn:
            return asdict(_get_service(conn).create_account(
                body.name, _normalize_market(body.market), body.base_currency, body.strategy_task_id
            ))
    except ValueError as exc:
        _error(exc)
    except TargetMaterializerUnavailable as exc:
        _materializer_error(exc)


@router.get("/accounts")
def list_accounts(include_inactive: bool = Query(False)):
    with _connection_scope() as conn:
        return [asdict(a) for a in _get_service(conn).list_accounts(include_inactive)]


@router.get("/accounts/{account_id}")
def get_account(account_id: int):
    try:
        with _connection_scope() as conn:
            return asdict(_get_service(conn).get_account(account_id))
    except ValueError as exc:
        _error(exc)
    except TargetMaterializerUnavailable as exc:
        _materializer_error(exc)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    try:
        with _connection_scope() as conn:
            return asdict(_get_service(conn).soft_delete_account(account_id))
    except ValueError as exc:
        _error(exc)


@router.post("/accounts/{account_id}/strategy")
def bind_strategy(account_id: int, body: StrategyBindingRequest):
    try:
        with _connection_scope() as conn:
            return asdict(_get_service(conn).bind_strategy(account_id, body.task_id))
    except ValueError as exc:
        _error(exc)
    except TargetMaterializerUnavailable as exc:
        _materializer_error(exc)


@router.delete("/accounts/{account_id}/strategy")
def unbind_strategy(account_id: int):
    try:
        with _connection_scope() as conn:
            return asdict(_get_service(conn).unbind_strategy(account_id))
    except ValueError as exc:
        _error(exc)


@router.post("/trades", status_code=201)
def create_trade(body: TradeCreateRequest):
    try:
        with _connection_scope() as conn:
            trade = record_trade(
                body.account_id, body.symbol, body.side, body.quantity, body.price,
                body.trade_date, body.fee, body.tax, conn,
            )
            return {"id": trade.id}
    except ValueError as exc:
        _error(exc)


@router.get("/trades")
def list_trades(
    account_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    symbol: str | None = Query(None),
    side: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    with _connection_scope() as conn:
        repo = AccountRepository(conn)
        accounts = repo.list_accounts(include_inactive=account_id is not None)
        if account_id is not None:
            accounts = [account for account in accounts if account.id == account_id]
        items = []
        for account in accounts:
            for trade in repo.list_trades(account.id):
                if date_from and trade["trade_date"] < date_from:
                    continue
                if date_to and trade["trade_date"] > date_to:
                    continue
                if symbol and trade["symbol"] != symbol:
                    continue
                if side and trade["direction"] != side:
                    continue
                items.append({
                    "id": trade["id"], "account_id": account.id, "symbol": trade["symbol"],
                    "market": account.market.lower(), "currency": account.base_currency,
                    "trade_date": trade["trade_date"], "side": trade["direction"],
                    "quantity": trade["shares"], "price": trade["price"],
                    "fee": trade["fee"], "tax": trade["tax"], "created_at": trade["created_at"],
                })
        items.sort(key=lambda item: (item["trade_date"], item["id"]))
        total = len(items)
        start = (page - 1) * page_size
        return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size}


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: int, account_id: int = Query(...)):
    with _connection_scope() as conn:
        try:
            delete_trade_service(account_id, trade_id, conn)
        except ValueError as exc:
            _error(exc)
        return {"deleted": 1}


@router.get("/accounts/{account_id}/holdings")
def list_holdings(account_id: int, as_of: str | None = Query(None)):
    try:
        with _connection_scope() as conn:
            return [asdict(holding) for holding in get_holdings(account_id, as_of, conn)]
    except ValueError as exc:
        _error(exc)


@router.get("/snapshot")
def get_snapshot(
    account_id: int | None = Query(None),
    as_of: str | None = Query(None),
    cost_method: str = Query("fifo"),
):
    from datetime import date

    try:
        with _connection_scope() as conn:
            return build_snapshot(
                as_of_date=as_of or date.today().isoformat(),
                account_id=account_id,
                cost_method=cost_method,
                store=_get_store(),
                connection=conn,
            )
    except ValueError as exc:
        _error(exc)


@router.get("/risk")
def get_risk():
    return _not_implemented()


@router.post("/fx/refresh")
def refresh_fx():
    return _not_implemented()


@router.get("/cash-ledger")
def list_cash_ledger():
    return _not_implemented()


@router.post("/cash-ledger")
def create_cash_ledger():
    return _not_implemented()


@router.delete("/cash-ledger/{entry_id}")
def delete_cash_ledger(entry_id: int):
    return _not_implemented()


@router.get("/corporate-actions")
def list_corporate_actions():
    return _not_implemented()


@router.post("/corporate-actions")
def create_corporate_action():
    return _not_implemented()


@router.delete("/corporate-actions/{action_id}")
def delete_corporate_action(action_id: int):
    return _not_implemented()


@router.get("/imports/csv/brokers")
def list_import_brokers():
    return _not_implemented()


@router.post("/imports/csv/parse")
def parse_csv_import():
    return _not_implemented()


@router.post("/imports/csv/commit")
def commit_csv_import():
    return _not_implemented()
