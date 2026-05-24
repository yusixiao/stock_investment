"""§2 市值/股价(最新收盘 + 总股本/总市值 + 流通 A 股/流通市值)。

明确区分总股本(TOTAL_SHARE)与流通 A 股(A_FREE_SHARE),避免下游 LLM 误读。
"""

from __future__ import annotations


def _fmt_million(v: float) -> str:
    return f"{v / 1e6:,.0f}"


def build(ref, *, store, stock_index, indicators) -> str:
    rows = []
    try:
        rows = store.query_qfq_kline_for_section(ref.code, limit=1, order="desc") or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §2 市值/股价\n\n- 当前价:—(数据缺失)\n"

    last = rows[0]
    price = float(last["close"])
    date = last["date"]

    # 总股本(含限售)— 用于"总市值"
    total_share = None
    try:
        ts = store.query_total_shares_for_section(ref.code)
        total_share = float(ts) if ts else None
    except Exception:  # noqa: BLE001
        total_share = None
    total_mcap = price * total_share if total_share else None

    # 流通 A 股(A_FREE_SHARE)— 用于"流通市值"
    free_share = None
    try:
        fs = store.query_circulating_shares_for_section(ref.code)
        free_share = float(fs) if fs else None
    except Exception:  # noqa: BLE001
        free_share = None
    free_mcap = price * free_share if free_share else None

    lines = [
        "## §2 市值/股价",
        "",
        f"- 最新收盘价:**{price:.2f}**({date})",
        (f"- 总股本(股):{total_share:,.0f}" if total_share else "- 总股本:—"),
        (
            f"- 总市值(百万元):{_fmt_million(total_mcap)}"
            if total_mcap
            else "- 总市值:—"
        ),
        (f"- 流通 A 股(股):{free_share:,.0f}" if free_share else "- 流通 A 股:—"),
        (
            f"- 流通市值(百万元):{_fmt_million(free_mcap)}"
            if free_mcap
            else "- 流通市值:—"
        ),
    ]
    return "\n".join(lines) + "\n"
