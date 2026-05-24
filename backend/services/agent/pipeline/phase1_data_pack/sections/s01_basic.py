"""§1 基础信息(代码 / 名称 / 上市结构 / 币种 / 行业)。"""

from __future__ import annotations

_CURRENCY = {"A": "CNY", "HK": "HKD", "US": "USD"}
_MARKET_LABEL = {"A": "A 股", "HK": "港股", "US": "美股"}


def build(ref, *, store, stock_index, indicators) -> str:
    industry = "—"
    try:
        # stock_index 期 1 暂未提供 get_industry,降级到 "—"
        getter = getattr(stock_index, "get_industry", None)
        if callable(getter):
            industry = getter(ref.code) or "—"
    except Exception:  # noqa: BLE001
        industry = "—"

    lines = [
        "## §1 基础信息",
        "",
        f"- 股票代码:**{ref.code}**",
        f"- 公司名称:{ref.name}",
        f"- 上市结构:{_MARKET_LABEL.get(ref.market, ref.market)}",
        f"- 报表币种:{_CURRENCY.get(ref.market, '—')}",
        f"- 所属行业:{industry}",
    ]
    return "\n".join(lines) + "\n"
