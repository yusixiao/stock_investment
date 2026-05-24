"""§4P 母公司资产负债表(A 股专属;港股/美股返回 None)。"""

from __future__ import annotations

from typing import Optional

from services.agent.pipeline.phase1_data_pack.sections._table import (
    fmt_million,
    md_table,
)

PARENT_BALANCE_FIELDS = [
    ("TOTAL_ASSETS", "总资产(母公司)"),
    ("TOTAL_LIABILITIES", "总负债(母公司)"),
    ("TOTAL_EQUITY", "股东权益(母公司)"),
    ("MONETARY_FUND", "货币资金(母公司)"),
    ("LONG_EQUITY_INVEST", "对子公司长投(母公司)"),
]


def build(ref, *, store, stock_index, indicators) -> Optional[str]:
    if ref.market != "A":
        return None
    try:
        rows = (
            store.query_financial_for_section(ref.code, table="balance_parent", years=5)
            or []
        )
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §4P 母公司资产负债表(近 5 年)\n\n母公司数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [
        [label] + [fmt_million(r.get(key)) for r in rows]
        for key, label in PARENT_BALANCE_FIELDS
    ]
    return "## §4P 母公司资产负债表(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"
