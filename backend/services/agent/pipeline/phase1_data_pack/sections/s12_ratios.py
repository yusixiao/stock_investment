"""§12 关键比率(近 5 年)。"""

from __future__ import annotations

from services.agent.pipeline.phase1_data_pack.sections._table import (
    fmt_num,
    md_table,
)

RATIO_FIELDS = [
    ("ROEJQ", "ROE(%)"),
    ("ROAJQ", "ROA(%)"),
    ("GROSSPROFIT_MARGIN", "毛利率(%)"),
    ("NETPROFIT_MARGIN", "净利率(%)"),
    ("DEBT_ASSET_RATIO", "资产负债率(%)"),
    ("CURRENT_RATIO", "流动比率"),
]


def build(ref, *, store, stock_index, indicators) -> str:
    try:
        rows = store.query_financial(ref.code, table="indicator", years=5) or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §12 关键比率(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [
        [label] + [fmt_num(r.get(key), 2) for r in rows] for key, label in RATIO_FIELDS
    ]
    return "## §12 关键比率(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"
