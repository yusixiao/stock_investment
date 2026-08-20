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
