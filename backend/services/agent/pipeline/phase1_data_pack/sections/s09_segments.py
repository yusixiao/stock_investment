"""§9 主营业务拆分(eastmoney 暂未接入,留占位)。"""

from __future__ import annotations

from services.agent.pipeline.phase1_data_pack.sections._table import (
    fmt_num,
    md_table,
)


def build(ref, *, store, stock_index, indicators) -> str:
    segs = []
    try:
        getter = getattr(store, "query_business_segments", None)
        if callable(getter):
            segs = getter(ref.code) or []
    except Exception:  # noqa: BLE001
        segs = []
    if not segs:
        return "## §9 主营拆分\n\n—(eastmoney 主营拆分暂未接入)\n"
    rows = [
        [
            s.get("segment", "—"),
            fmt_num(s.get("revenue_pct"), 1) + "%",
            fmt_num(s.get("gross_margin"), 1) + "%",
        ]
        for s in segs
    ]
    return "## §9 主营拆分\n\n" + md_table(["业务", "营收占比", "毛利率"], rows) + "\n"
