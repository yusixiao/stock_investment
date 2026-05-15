from dataclasses import dataclass

from backend.adapters.base import (
    MarketDataAdapter,
    BasicDataAdapter,
    FinancialDataAdapter,
    EventDataAdapter,
)


@dataclass
class DataSource:
    """统一数据源入口，内部路由到具体 adapter。可配置切换。"""

    market: MarketDataAdapter
    financial: FinancialDataAdapter
    basic: BasicDataAdapter
    event: EventDataAdapter


def create_default_data_source() -> DataSource:
    from backend.adapters.baostock_adapter import BaoStockAdapter
    from backend.adapters.eastmoney_adapter import EastMoneyAdapter

    baostock = BaoStockAdapter()
    eastmoney = EastMoneyAdapter()
    return DataSource(
        market=baostock,
        financial=eastmoney,
        basic=baostock,
        event=baostock,
    )
