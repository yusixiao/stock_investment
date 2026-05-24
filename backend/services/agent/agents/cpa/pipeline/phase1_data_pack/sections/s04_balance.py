"""§4 资产负债表(近 5 年)。"""

from __future__ import annotations

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections._table import (
    fmt_million,
    fmt_num,
    md_table,
)

BALANCE_FIELDS = [
    ("TOTAL_ASSETS", "总资产"),
    ("TOTAL_LIABILITIES", "总负债"),
    ("TOTAL_EQUITY", "股东权益"),
    ("TOTAL_CURRENT_ASSETS", "流动资产"),
    ("TOTAL_CURRENT_LIAB", "流动负债"),
    ("MONETARY_FUND", "货币资金"),
    ("INVENTORIES", "存货"),
    ("FIXED_ASSETS", "固定资产"),
    ("INTANGIBLE_ASSETS", "无形资产"),
    ("GOODWILL", "商誉"),
]


def build(ref, *, store, stock_index, indicators) -> str:
    try:
        rows = (
            store.query_financial_for_section(ref.code, table="balance", years=5) or []
        )
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §4 资产负债表(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [
        [label] + [fmt_million(r.get(key)) for r in rows]
        for key, label in BALANCE_FIELDS
    ]
    table_rows.append(["每股净资产(元/股)"] + [fmt_num(r.get("BPS"), 2) for r in rows])
    return "## §4 资产负债表(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"
