from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    market: str
    base_currency: str
    strategy_task_id: str | None
    strategy_bound_at: str | None
    strategy_unbound_at: str | None
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Trade:
    id: int
    account_id: int
    symbol: str
    side: str
    quantity: int
    price: float
    trade_date: str
    fee: float
    tax: float
    realized_pnl: float


@dataclass(frozen=True)
class Holding:
    account_id: int
    symbol: str
    actual_shares: int
    average_cost: float
    realized_pnl: float
    target_quantity: int = 0
    reference_price: float | None = None
    target_status: str | None = None
    remaining_quantity: int = 0
