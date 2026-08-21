from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyMonitor:
    id: int
    name: str
    strategy_class: str
    filepath: str
    params: dict[str, Any]
    market: str
    frequency: str
    symbols: list[str] | None
    is_active: bool
    next_run_date: str | None
    last_run_at: str | None
    last_run_status: str
    last_error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StrategyRun:
    id: int
    monitor_id: int
    scheduled_date: str
    started_at: str
    finished_at: str | None
    status: str
    task_id: str | None
    result: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True)
class StockPriceMonitor:
    id: int
    market: str
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
