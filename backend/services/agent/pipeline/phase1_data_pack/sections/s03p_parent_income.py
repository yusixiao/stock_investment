"""§3P 母公司利润表(A 股专属;港股/美股返回 None)。"""

from __future__ import annotations

from typing import Optional

from services.agent.pipeline.phase1_data_pack.sections._table import (
    fmt_million,
    md_table,
)

PARENT_INCOME_FIELDS = [
    ("TOTAL_OPERATE_INCOME", "营业总收入(母公司)"),
    ("OPERATE_PROFIT", "营业利润(母公司)"),
    ("NETPROFIT", "净利润(母公司)"),
    ("PARENT_NETPROFIT", "母公司净利润"),
]


def build(ref, *, store, stock_index, indicators) -> Optional[str]:
    if ref.market != "A":
        return None
    try:
        rows = (
            store.query_financial_for_section(ref.code, table="income_parent", years=5)
            or []
        )
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §3P 母公司利润表(近 5 年)\n\n母公司数据缺失(eastmoney 未提供母表)\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [
        [label] + [fmt_million(r.get(key)) for r in rows]
        for key, label in PARENT_INCOME_FIELDS
    ]
    return "## §3P 母公司利润表(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"
