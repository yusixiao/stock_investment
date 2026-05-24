"""§11 历史价格(近 5 年周线摘要)。"""

from __future__ import annotations

from services.agent.pipeline.phase1_data_pack.sections._table import (
    fmt_num,
    md_table,
)


def build(ref, *, store, stock_index, indicators) -> str:
    try:
        rows = store.query_qfq_kline_for_section(ref.code, freq="W", years=5) or []
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return "## §11 历史价格(近 5 年周线)\n\n数据缺失\n"
    closes = [float(r["close"]) for r in rows]
    high_all = max(float(r["high"]) for r in rows)
    low_all = min(float(r["low"]) for r in rows)
    ret = (closes[-1] / closes[0] - 1) * 100 if closes[0] else 0.0
    summary = (
        f"- 区间最高:{high_all:,.2f}  最低:{low_all:,.2f}\n"
        f"- 期初/期末收盘:{closes[0]:,.2f} → {closes[-1]:,.2f}\n"
        f"- 区间涨跌幅:**{ret:+.1f}%**\n"
    )
    sample = rows[:3] + (rows[-3:] if len(rows) > 6 else [])
    table = md_table(
        ["日期", "收盘"], [[str(r["date"]), fmt_num(r["close"], 2)] for r in sample]
    )
    return "## §11 历史价格(近 5 年周线)\n\n" + summary + "\n" + table + "\n"
