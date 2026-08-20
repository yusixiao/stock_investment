"""固定一次回测使用的数据上下文,不复制全市场数据。"""

from __future__ import annotations

from dataclasses import dataclass

from services.backtest import data_cache
from services.backtest.data_cache import MarketBundle, SlicedBundle, slice_bundle


@dataclass(frozen=True)
class BacktestDataSnapshot:
    """某次回测/扫描绑定的市场数据视图和版本元信息。

    ``sliced`` 只包含字典视图,其中的 DataFrame 仍归 ``MarketBundle`` 所有,
    因此创建 Snapshot 不会复制一份全市场数据。
    """

    market: str
    bundle: MarketBundle
    sliced: SlicedBundle
    symbols: tuple[str, ...]
    start_date: str | None
    end_date: str | None
    data_as_of: str | None
    stale: bool
    generation: int
    market_version: int | None
    refresh_id: str | None

    def data_context(self) -> dict[str, object]:
        """返回面向用户的最小数据上下文,隐藏内部追踪字段。"""
        return {
            "market": self.market,
            "data_as_of": self.data_as_of,
            "stale": self.stale,
        }


def create_snapshot(
    bundle: MarketBundle | None,
    market: str,
    symbols: list[str] | None,
    start_date: str | None,
    end_date: str | None,
    *,
    generation: int | None = None,
    refresh_id: str | None = None,
    market_version: int | None = None,
    stale: bool | None = None,
) -> BacktestDataSnapshot:
    """从已加载的 ``MarketBundle`` 创建轻量 Snapshot。

    不负责触发加载；没有 bundle 或切片结果为空时直接失败,避免回测路径
    隐式执行全市场 IO。
    """
    normalized_market = market.upper()
    if bundle is None:
        raise ValueError(f"No loaded bundle for market {normalized_market}")

    sliced = slice_bundle(bundle, symbols, start_date, end_date)
    if not sliced.stock_data:
        raise ValueError(f"Snapshot has no stock data for market {normalized_market}")

    status = data_cache.get_status(normalized_market)
    return BacktestDataSnapshot(
        market=normalized_market,
        bundle=bundle,
        sliced=sliced,
        symbols=tuple(sliced.stock_data),
        start_date=start_date,
        end_date=end_date,
        data_as_of=bundle.last_date,
        stale=status["stale"] if stale is None else stale,
        generation=status["generation"] if generation is None else generation,
        market_version=(
            status["market_version"] if market_version is None else market_version
        ),
        refresh_id=status["refresh_id"] if refresh_id is None else refresh_id,
    )
