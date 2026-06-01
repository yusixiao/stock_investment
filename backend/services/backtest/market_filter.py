"""市场标识解析 + 港股通子集过滤。

回测 / 雷达 / 选股的 `market` 入参除物理市场 {A, HK, US} 外,新增虚拟市场
`HK_CONNECT`(港股通成分股)。该虚拟市场:

  - 复用 HK 市场的 MarketBundle / 数据缓存(物理数据完全一致)
  - 仅在 symbols 维度按 services.hk_connect_updater.get_latest_hk_connect_codes()
    限定到当前快照的港股通成分股(601 只)
  - 任务历史 / 前端展示保留 'HK_CONNECT' 标签;data_cache.get_market 必须收到 'HK'

⚠️ 港股通成分股仅当前快照,无 point-in-time 历史。回测会引入 ~2-3% look-ahead +
survivorship bias,粗筛/资产配置回测可接受,严格 PIT 策略不适用。
"""

from __future__ import annotations

HK_CONNECT_MARKET = "HK_CONNECT"
SUPPORTED_DISPLAY_MARKETS = ("A", "HK", "US", HK_CONNECT_MARKET)


def resolve_data_market(market: str) -> str:
    """把展示侧 market 映射到物理数据 market(给 data_cache.get_market 用)。

    HK_CONNECT → HK,其余原样返回(大小写规范化为大写)。
    """
    m = (market or "A").upper()
    if m == HK_CONNECT_MARKET:
        return "HK"
    return m


def apply_market_filter(
    market: str, requested_symbols: list[str] | None
) -> list[str] | None:
    """按 market 语义过滤 symbol 列表。

    - HK_CONNECT:
        * requested_symbols 为 None → 返回全部港股通成分股(.HK 后缀)
        * requested_symbols 非空 → 返回与港股通成分股的交集(顺序保留)
    - 其他市场:原样返回(passthrough)

    ⚠️ 调用 services.hk_connect_updater 读 parquet,parquet 缺失时 connect_set
    为空,HK_CONNECT 会得到空列表 / 空交集 — 上游路由会因此报"切片后无 K 线"。
    """
    if (market or "").upper() != HK_CONNECT_MARKET:
        return requested_symbols

    # 延迟 import 避免模块互相 import
    from services.hk_connect_updater import get_latest_hk_connect_codes

    connect_codes = get_latest_hk_connect_codes()
    connect_symbols = {f"{c}.HK" for c in connect_codes}

    if not requested_symbols:
        return sorted(connect_symbols)

    # 保留用户原始顺序的交集
    return [s for s in requested_symbols if s in connect_symbols]
