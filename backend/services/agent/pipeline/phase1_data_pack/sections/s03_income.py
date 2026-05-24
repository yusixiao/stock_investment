"""§3 利润表(近 5 年)。"""

from __future__ import annotations

from services.agent.pipeline.phase1_data_pack.sections._table import (
    fmt_million,
    fmt_num,
    md_table,
)

INCOME_FIELDS = [
    ("TOTAL_OPERATE_INCOME", "营业总收入"),
    ("OPERATE_COST", "营业成本"),
    ("GROSS_PROFIT", "毛利"),
    ("OPERATE_PROFIT", "营业利润"),
    ("NETPROFIT", "净利润"),
    ("PARENT_NETPROFIT", "归母净利润"),
    ("DEDUCT_PARENT_NETPROFIT", "扣非归母净利润"),
]


def build(ref, *, store, stock_index, indicators) -> str:
    try:
        rows = (
            store.query_financial_for_section(ref.code, table="income", years=5) or []
        )
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §3 利润表(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [
        [label] + [fmt_million(r.get(key)) for r in rows]
        for key, label in INCOME_FIELDS
    ]
    table_rows.append(
        ["每股收益(元/股)"] + [fmt_num(r.get("BASIC_EPS"), 2) for r in rows]
    )
    return "## §3 利润表(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"
