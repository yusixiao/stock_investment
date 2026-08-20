from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.backtest.task_manager import task_manager
from services.portfolio.account_service import (
    AccountService,
    TargetMaterializerUnavailable,
)
from services.portfolio.strategy_targets import materialize_targets
from services.portfolio.db import get_connection, init_db
from services.portfolio.repository import AccountRepository

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio-v1"])


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    market: str = Field(min_length=1)
    base_currency: str = Field(min_length=1)
    strategy_task_id: str | None = None


class StrategyBindingRequest(BaseModel):
    task_id: str = Field(min_length=1)


def _get_connection():
    conn = get_connection()
    init_db(conn)
    return conn


def _get_task_manager():
    return task_manager


def _get_materializer():
    return materialize_targets


def _get_service() -> AccountService:
    return AccountService(
        AccountRepository(_get_connection()),
        _get_task_manager(),
        target_materializer=_get_materializer(),
    )


def _error(exc: ValueError):
    status = 404 if str(exc) == "account not found" else 409
    raise HTTPException(status_code=status, detail=str(exc))


def _materializer_error(exc: TargetMaterializerUnavailable):
    raise HTTPException(status_code=503, detail=str(exc))


@router.post("/accounts", status_code=201)
def create_account(body: AccountCreateRequest):
    try:
        return asdict(_get_service().create_account(
            body.name, body.market, body.base_currency, body.strategy_task_id
        ))
    except ValueError as exc:
        _error(exc)
    except TargetMaterializerUnavailable as exc:
        _materializer_error(exc)


@router.get("/accounts")
def list_accounts(include_inactive: bool = Query(False)):
    return [asdict(a) for a in _get_service().list_accounts(include_inactive)]


@router.get("/accounts/{account_id}")
def get_account(account_id: int):
    try:
        return asdict(_get_service().get_account(account_id))
    except ValueError as exc:
        _error(exc)
    except TargetMaterializerUnavailable as exc:
        _materializer_error(exc)


@router.post("/accounts/{account_id}/strategy")
def bind_strategy(account_id: int, body: StrategyBindingRequest):
    try:
        return asdict(_get_service().bind_strategy(account_id, body.task_id))
    except ValueError as exc:
        _error(exc)
    except TargetMaterializerUnavailable as exc:
        _materializer_error(exc)


@router.delete("/accounts/{account_id}/strategy")
def unbind_strategy(account_id: int):
    try:
        return asdict(_get_service().unbind_strategy(account_id))
    except ValueError as exc:
        _error(exc)
