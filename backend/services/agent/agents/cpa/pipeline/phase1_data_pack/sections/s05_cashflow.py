"""§5 现金流量表(近 5 年)。"""

from __future__ import annotations

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections._table import (
    fmt_million,
    md_table,
)

CASHFLOW_FIELDS = [
    ("NETCASH_OPERATE", "经营性现金流"),
    ("NETCASH_INVEST", "投资性现金流"),
    ("NETCASH_FINANCE", "筹资性现金流"),
    ("END_CASH", "期末现金及等价物"),
    ("DEPRECIATION_FA", "固定资产折旧"),
    ("CONSTRUCT_LONG_ASSET", "构建长期资产支出(资本支出)"),
]


def build(ref, *, store, stock_index, indicators) -> str:
    try:
        rows = (
            store.query_financial_for_section(ref.code, table="cashflow", years=5) or []
        )
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §5 现金流量表(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: r["REPORT_DATE"], reverse=True)[:5]
    headers = ["指标(百万元)"] + [r["REPORT_DATE"] for r in rows]
    table_rows = [
        [label] + [fmt_million(r.get(key)) for r in rows]
        for key, label in CASHFLOW_FIELDS
    ]
    return "## §5 现金流量表(近 5 年)\n\n" + md_table(headers, table_rows) + "\n"
