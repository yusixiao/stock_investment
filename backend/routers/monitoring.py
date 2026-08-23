from __future__ import annotations

from datetime import date, datetime
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.monitoring.repository import FREQUENCIES, MonitoringRepository
from services.monitoring.strategy_monitor import (
    get_monitoring_connection,
    initial_run_date,
    submit_strategy_run,
)
from config import DEPLOYED_STRATEGY_DIR
from services.backtest.strategy_loader import load_strategy_from_file
from services.market_data.duckdb_store import get_store as get_monitoring_store


router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])
Market = Literal["A", "HK", "US"]


class StrategyMonitorResponse(BaseModel):
    id: int
    name: str
    strategy_class: str
    filepath: str
    params: dict[str, Any]
    market: Market
    frequency: str
    symbols: list[str] | None
    is_active: bool
    next_run_date: str | None
    last_run_at: str | None
    last_run_status: str
    last_error: str | None
    created_at: str
    updated_at: str


class StrategyRunResponse(BaseModel):
    id: int
    monitor_id: int
    scheduled_date: str
    started_at: str
    finished_at: str | None
    status: str
    task_id: str | None
    result: dict[str, Any] | None
    error: str | None


class StockMonitorResponse(BaseModel):
    id: int
    market: Market
    symbol: str
    name: str | None
    threshold_price: float
    is_active: bool
    state: str
    last_price: float | None
    last_price_date: str | None
    last_triggered_at: str | None
    created_at: str
    updated_at: str


class StockEventResponse(BaseModel):
    id: int
    monitor_id: int
    market: Market
    symbol: str
    observed_price: float
    threshold_price: float
    observed_date: str
    triggered_at: str
    status: str


class StrategyMonitorPage(BaseModel):
    items: list[StrategyMonitorResponse]
    total: int
    limit: int
    offset: int


class StrategyRunPage(BaseModel):
    items: list[StrategyRunResponse]
    total: int
    limit: int
    offset: int


class StockMonitorPage(BaseModel):
    items: list[StockMonitorResponse]
    total: int
    limit: int
    offset: int


class StockEventPage(BaseModel):
    items: list[StockEventResponse]
    total: int
    limit: int
    offset: int


class MonitorCenterResponse(BaseModel):
    strategies: list[StrategyMonitorResponse]
    strategy_runs: dict[int, list[StrategyRunResponse]]
    stocks: list[StockMonitorResponse]
    stock_events: dict[int, list[StockEventResponse]]
    generated_at: str


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

    @model_validator(mode="after")
    def valid_symbols(self):
        _validate_symbols(self.market, self.symbols)
        return self


class StrategyMonitorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
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

    @model_validator(mode="after")
    def valid_symbols(self):
        if self.market is not None and self.symbols is not None:
            _validate_symbols(self.market, self.symbols)
        return self


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
    model_config = ConfigDict(extra="forbid")
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
    patterns = {
        "A": r"^\d{6}(?:\.(?:SH|SZ))?$",
        "HK": r"^\d{5}(?:\.HK)?$",
        "US": r"^[A-Z][A-Z0-9.-]*$",
    }
    if re.fullmatch(patterns[market], symbol) is None:
        raise ValueError(f"symbol is invalid for market {market}")


def _validate_symbols(market: str, symbols: list[str] | None) -> None:
    if symbols is None:
        return
    if not symbols:
        raise ValueError("symbols must not be empty")
    for symbol in symbols:
        _validate_symbol(market, symbol)


def _dump(value: Any) -> dict[str, Any]:
    return {key: getattr(value, key) for key in value.__dataclass_fields__}


def _repo():
    conn = get_monitoring_connection()
    return conn, MonitoringRepository(conn)


def _close_connection(conn) -> None:
    conn.close()


def _commit(conn) -> None:
    conn.commit()


def _validate_strategy_definition(filepath: str, strategy_class: str, params: dict[str, Any]) -> None:
    root = DEPLOYED_STRATEGY_DIR.resolve()
    path = Path(filepath).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("strategy filepath must be inside the deployed strategy directory") from exc
    if path.suffix != ".py" or not path.is_file():
        raise ValueError("strategy filepath is not a published file")
    try:
        classes = load_strategy_from_file(path)
    except Exception as exc:
        raise ValueError(f"published strategy cannot be loaded: {exc}") from exc
    strategy_cls = next((cls for cls in classes if cls.__name__ == strategy_class), None)
    if strategy_cls is None:
        raise ValueError(f"strategy class not found: {strategy_class}")
    try:
        strategy_cls(param_overrides=params)
    except Exception as exc:
        raise ValueError(f"strategy config invalid: {exc}") from exc


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def _domain_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message:
        return HTTPException(status_code=404, detail=message)
    if "inactive" in message or "already" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=422, detail=message)


@router.get("/strategy-monitors", response_model=StrategyMonitorPage)
def list_strategy_monitors(include_inactive: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        return _page([_dump(item) for item in repo.list_strategy_monitors(include_inactive)], limit, offset)
    finally:
        _close_connection(conn)


@router.get("/center", response_model=MonitorCenterResponse)
def get_monitor_center(history_limit: int = Query(5, ge=1, le=50)):
    conn, repo = _repo()
    try:
        snapshot = repo.get_monitor_center(recent_limit=history_limit)
        return {
            "strategies": [_dump(item) for item in snapshot["strategies"]],
            "strategy_runs": {
                monitor_id: [_dump(run) for run in runs]
                for monitor_id, runs in snapshot["strategy_runs"].items()
            },
            "stocks": [_dump(item) for item in snapshot["stocks"]],
            "stock_events": snapshot["stock_events"],
            "generated_at": datetime.now().isoformat(),
        }
    finally:
        _close_connection(conn)


@router.post("/strategy-monitors", status_code=201, response_model=StrategyMonitorResponse)
def create_strategy_monitor(payload: StrategyMonitorCreate):
    conn, repo = _repo()
    try:
        values = payload.model_dump()
        _validate_strategy_definition(values["filepath"], values["strategy_class"], values["params"])
        if values["next_run_date"] is None:
            values["next_run_date"] = initial_run_date(
                values["frequency"], values["market"], get_monitoring_store()
            )
        result = repo.create_strategy_monitor(**values)
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.patch("/strategy-monitors/{monitor_id}", response_model=StrategyMonitorResponse)
def update_strategy_monitor(monitor_id: int, payload: StrategyMonitorPatch):
    conn, repo = _repo()
    try:
        changes = payload.model_dump(exclude_unset=True)
        current = repo.get_strategy_monitor(monitor_id)
        if current is None:
            raise _not_found("strategy monitor not found")
        _validate_symbols(changes.get("market", current.market), changes.get("symbols", current.symbols))
        _validate_strategy_definition(
            changes.get("filepath", current.filepath),
            changes.get("strategy_class", current.strategy_class),
            changes.get("params", current.params),
        )
        result = repo.update_strategy_monitor(monitor_id, **changes)
        _commit(conn)
        return _dump(result)
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.delete("/strategy-monitors/{monitor_id}", response_model=StrategyMonitorResponse)
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


@router.post("/strategy-monitors/{monitor_id}/run", status_code=201, response_model=StrategyRunResponse)
def run_strategy_monitor(monitor_id: int, payload: ManualRun):
    conn, repo = _repo()
    try:
        monitor = repo.get_strategy_monitor(monitor_id)
        if monitor is None:
            raise _not_found("strategy monitor not found")
        if not monitor.is_active:
            raise HTTPException(status_code=409, detail="strategy monitor is inactive")
        if repo.get_strategy_run(monitor_id, payload.as_of_date) is not None:
            raise HTTPException(status_code=409, detail="strategy run already exists for scheduled date")
        run = repo.create_strategy_run(monitor_id, payload.as_of_date)
        try:
            # This seam is deliberately a bounded, current-date snapshot scan.
            # Historical/full backtests must not be wired into this HTTP handler.
            _commit(conn)
            submit_strategy_run(monitor, run, payload.as_of_date)
        except Exception as exc:  # noqa: BLE001
            error = f"strategy execution dispatch failed: {exc}"
            repo.finish_strategy_run(run.id, "failed", error=error)
            _commit(conn)
            raise HTTPException(status_code=500, detail=error) from exc
        return _dump(run)
    except HTTPException:
        raise
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.get("/strategy-monitors/{monitor_id}/runs", response_model=StrategyRunPage)
def list_strategy_runs(monitor_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        if repo.get_strategy_monitor(monitor_id) is None:
            raise _not_found("strategy monitor not found")
        return _page([_dump(item) for item in repo.list_strategy_runs(monitor_id)], limit, offset)
    finally:
        _close_connection(conn)


@router.get("/stock-monitors", response_model=StockMonitorPage)
def list_stock_monitors(include_inactive: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        return _page([_dump(item) for item in repo.list_stock_monitors(include_inactive)], limit, offset)
    finally:
        _close_connection(conn)


@router.post("/stock-monitors", status_code=201, response_model=StockMonitorResponse)
def create_stock_monitor(payload: StockMonitorCreate):
    conn, repo = _repo()
    try:
        result = repo.create_stock_monitor(**payload.model_dump())
        _commit(conn)
        return _dump(result)
    finally:
        _close_connection(conn)


@router.patch("/stock-monitors/{monitor_id}", response_model=StockMonitorResponse)
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


@router.delete("/stock-monitors/{monitor_id}", response_model=StockMonitorResponse)
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
            if monitor.state != "armed":
                raise HTTPException(status_code=409, detail="stock monitor is not armed")
            result = repo.pause_stock_monitor(monitor_id)
        else:
            if monitor.state != "paused":
                raise HTTPException(status_code=409, detail="stock monitor is not paused")
            result = repo.resume_stock_monitor(monitor_id)
        _commit(conn)
        return _dump(result)
    except HTTPException:
        raise
    except ValueError as exc:
        raise _domain_error(exc) from exc
    finally:
        _close_connection(conn)


@router.post("/stock-monitors/{monitor_id}/pause", response_model=StockMonitorResponse)
def pause_stock_monitor(monitor_id: int):
    return _change_stock_state(monitor_id, "pause")


@router.post("/stock-monitors/{monitor_id}/resume", response_model=StockMonitorResponse)
def resume_stock_monitor(monitor_id: int):
    return _change_stock_state(monitor_id, "resume")


@router.get("/stock-monitors/{monitor_id}/events", response_model=StockEventPage)
def list_stock_events(monitor_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn, repo = _repo()
    try:
        if repo.get_stock_monitor(monitor_id) is None:
            raise _not_found("stock monitor not found")
        events = repo.list_stock_events(monitor_id)
        return _page(events, limit, offset)
    finally:
        _close_connection(conn)
