"""§2 市值/股价(最新收盘 + 流通股本 + 流通市值)。"""

from __future__ import annotations


def _fmt_million(v: float) -> str:
    return f"{v / 1e6:,.0f}"


def build(ref, *, store, stock_index, indicators) -> str:
    rows = []
    try:
        rows = store.query_qfq_kline(ref.code, limit=1, order="desc") or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §2 市值/股价\n\n- 当前价:—(数据缺失)\n"

    last = rows[0]
    price = float(last["close"])
    date = last["date"]

    shares = None
    try:
        shares = float(store.query_circulating_shares(ref.code) or 0) or None
    except Exception:  # noqa: BLE001
        shares = None
    market_cap = price * shares if shares else None

    lines = [
        "## §2 市值/股价",
        "",
        f"- 最新收盘价:**{price:.2f}**({date})",
        (f"- 流通股本(股):{shares:,.0f}" if shares else "- 流通股本:—"),
        (
            f"- 流通市值(百万元):{_fmt_million(market_cap)}"
            if market_cap
            else "- 流通市值:—"
        ),
    ]
    return "\n".join(lines) + "\n"
