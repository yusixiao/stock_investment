"""§6 每股股息(近 5 年)。"""

from __future__ import annotations

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections._table import (
    fmt_num,
    md_table,
)


def build(ref, *, store, stock_index, indicators) -> str:
    try:
        rows = store.query_dividend_for_section(ref.code, years=5) or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §6 每股股息(近 5 年)\n\n数据缺失\n"
    rows = sorted(rows, key=lambda r: str(r["year"]), reverse=True)[:5]
    return (
        "## §6 每股股息(近 5 年)\n\n"
        + md_table(
            ["年度", "DPS(元/股)"],
            [[str(r["year"]), fmt_num(r.get("dps"), 2)] for r in rows],
        )
        + "\n"
    )
