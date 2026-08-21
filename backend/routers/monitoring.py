from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.monitoring.repository import FREQUENCIES, MonitoringRepository
from services.monitoring.strategy_monitor import (
    execute_strategy_current_date,
    get_monitoring_connection,
)


router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])
Market = Literal["A", "HK", "US"]


class StrategyMonitorCreate(BaseModel):
    name: str = Field(..., min_length=1)
    strategy_class: str = Field(..., min_length=1)
    filepath: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    market: Market
    frequency: str
    symbols: list[str] | None = None
    next_run_date: str | None = None

    @field_validator("frequency")
    @classmethod
    def valid_frequency(cls, value: str) -> str:
        if value not in FREQUENCIES:
            raise ValueError("frequency must be daily, weekly, monthly, or quarterly")
        return value


class StrategyMonitorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    strategy_class: str | None = Field(default=None, min_length=1)
    filepath: str | None = Field(default=None, min_length=1)
    params: dict[str, Any] | None = None
    market: Market | None = None
    frequency: str | None = None
    symbols: list[str] | None = None
    next_run_date: str | None = None

    @field_validator("frequency")
    @classmethod
    def valid_frequency(cls, value: str | None) -> str | None:
        if value is not None and value not in FREQUENCIES:
            raise ValueError("frequency must be daily, weekly, monthly, or quarterly")
        return value


class StockMonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market
    symbol: str = Field(..., min_length=1)
    threshold_price: float = Field(..., gt=0)

    @model_validator(mode="after")
    def valid_symbol(self):
        _validate_symbol(self.market, self.symbol)
        return self


class StockMonitorPatch(BaseModel):
    market: Market | None = None
    symbol: str | None = Field(default=None, min_length=1)
    threshold_price: float | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1)

    @field_validator("symbol")
    @classmethod
    def valid_symbol_shape(cls, value: str | None) -> str | None:
        if value is not None and any(char.isspace() for char in value):
            raise ValueError("symbol must not contain whitespace")
        return value


class ManualRun(BaseModel):
    as_of_date: str

    @field_validator("as_of_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("as_of_date must be YYYY-MM-DD") from exc
        return value


def _page(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    return {"items": items[offset : offset + limit], "total": len(items), "limit": limit, "offset": offset}


def _validate_symbol(market: str | None, symbol: str | None) -> None:
    if not market or not symbol or any(char.isspace() for char in symbol):
        raise ValueError("symbol is invalid")
    import re

    patterns = {
        "A": r"^\d{6}(?:\.(?:SH|SZ))?$",
        "HK": r"^\d{5}(?:\.HK)?$",
        "US": r"^[A-Z][A-Z0-9.-]*$",
    }
    if re.fullmatch(patterns[market], symbol) is None:
        raise ValueError(f"symbol is invalid for market {market}")


def _dump(value: Any) -> dict[str, Any]:
    return {key: getattr(value, key) for key in value.__dataclass_fields__}


def _repo():
    conn = get_monitoring_connection()
    return conn, MonitoringRepository(conn)


def _close_connection(conn) -> None:
    conn.close()


def _commit(conn) -> None:
    conn.commit()


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def _domain_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message:
        return HTTPException(status_code=404, detail=message)
    if "inactive" in message or "already" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("/strategy-monitors")
def list_strategy_monitors(include_inactive: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        return _page([_dump(item) for item in repo.list_strategy_monitors(include_inactive)], limit, offset)
    finally:
        _close_connection(conn)


@router.post("/strategy-monitors", status_code=201)
def create_strategy_monitor(payload: StrategyMonitorCreate):
    conn, repo = _repo()
    try:
        result = repo.create_strategy_monitor(**payload.model_dump())
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.patch("/strategy-monitors/{monitor_id}")
def update_strategy_monitor(monitor_id: int, payload: StrategyMonitorPatch):
    conn, repo = _repo()
    try:
        result = repo.update_strategy_monitor(monitor_id, **payload.model_dump(exclude_unset=True))
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.delete("/strategy-monitors/{monitor_id}")
def delete_strategy_monitor(monitor_id: int):
    conn, repo = _repo()
    try:
        result = repo.soft_delete_strategy_monitor(monitor_id)
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.post("/strategy-monitors/{monitor_id}/run", status_code=201)
def run_strategy_monitor(monitor_id: int, payload: ManualRun):
    conn, repo = _repo()
    try:
        monitor = repo.get_strategy_monitor(monitor_id)
        if monitor is None:
            raise _not_found("strategy monitor not found")
        if not monitor.is_active:
            raise HTTPException(status_code=409, detail="strategy monitor is inactive")
        run = repo.create_strategy_run(monitor_id, payload.as_of_date)
        outcome = execute_strategy_current_date(monitor, payload.as_of_date, None)
        if outcome.get("status") == "unexecuted":
            run = repo.finish_strategy_run(run.id, "failed", result=outcome, error=outcome.get("reason"))
        else:
            run = repo.finish_strategy_run(run.id, "success", result=outcome)
        _commit(conn)
        return _dump(run)
    except HTTPException:
        raise
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.get("/strategy-monitors/{monitor_id}/runs")
def list_strategy_runs(monitor_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        if repo.get_strategy_monitor(monitor_id) is None:
            raise _not_found("strategy monitor not found")
        return _page([_dump(item) for item in repo.list_strategy_runs(monitor_id)], limit, offset)
    finally:
        _close_connection(conn)


@router.get("/stock-monitors")
def list_stock_monitors(include_inactive: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        return _page([_dump(item) for item in repo.list_stock_monitors(include_inactive)], limit, offset)
    finally:
        _close_connection(conn)


@router.post("/stock-monitors", status_code=201)
def create_stock_monitor(payload: StockMonitorCreate):
    conn, repo = _repo()
    try:
        result = repo.create_stock_monitor(**payload.model_dump())
        _commit(conn)
        return _dump(result)
    finally:
        _close_connection(conn)


@router.patch("/stock-monitors/{monitor_id}")
def update_stock_monitor(monitor_id: int, payload: StockMonitorPatch):
    conn, repo = _repo()
    try:
        current = repo.get_stock_monitor(monitor_id)
        if current is None:
            raise _not_found("stock monitor not found")
        _validate_symbol(payload.market or current.market, payload.symbol or current.symbol)
        result = repo.update_stock_monitor(monitor_id, **payload.model_dump(exclude_unset=True))
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.delete("/stock-monitors/{monitor_id}")
def delete_stock_monitor(monitor_id: int):
    conn, repo = _repo()
    try:
        result = repo.soft_delete_stock_monitor(monitor_id)
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


def _change_stock_state(monitor_id: int, action: str):
    conn, repo = _repo()
    try:
        monitor = repo.get_stock_monitor(monitor_id)
        if monitor is None:
            raise _not_found("stock monitor not found")
        if not monitor.is_active:
            raise HTTPException(status_code=409, detail="stock monitor is inactive")
        if action == "pause":
            result = repo.pause_stock_monitor(monitor_id)
        else:
            result = repo.resume_stock_monitor(monitor_id)
        _commit(conn)
        return _dump(result)
    except HTTPException:
        raise
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.post("/stock-monitors/{monitor_id}/pause")
def pause_stock_monitor(monitor_id: int):
    return _change_stock_state(monitor_id, "pause")


@router.post("/stock-monitors/{monitor_id}/resume")
def resume_stock_monitor(monitor_id: int):
    return _change_stock_state(monitor_id, "resume")


@router.get("/stock-monitors/{monitor_id}/events")
def list_stock_events(monitor_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        if repo.get_stock_monitor(monitor_id) is None:
            raise _not_found("stock monitor not found")
        events = repo.list_stock_events(monitor_id)
        return _page(events, limit, offset)
    finally:
        _close_connection(conn)
