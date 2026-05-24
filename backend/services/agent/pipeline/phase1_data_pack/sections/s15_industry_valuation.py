"""§15 行业平均估值(中位数)。"""

from __future__ import annotations

from services.agent.pipeline.phase1_data_pack.sections._table import fmt_num


def build(ref, *, store, stock_index, indicators) -> str:
    summary = None
    try:
        getter = getattr(store, "query_industry_valuation_summary", None)
        if callable(getter):
            summary = getter(ref.code)
    except Exception:  # noqa: BLE001
        summary = None
    if not summary:
        return "## §15 行业平均估值\n\n—(行业数据缺失)\n"
    return (
        "## §15 行业平均估值\n\n"
        f"- 行业:{summary.get('industry', '—')}\n"
        f"- 行业 PE 中位数:{fmt_num(summary.get('pe_median'), 1)}\n"
        f"- 行业 PB 中位数:{fmt_num(summary.get('pb_median'), 1)}\n"
        f"- 样本数:{summary.get('sample_size', '—')}\n"
    )
