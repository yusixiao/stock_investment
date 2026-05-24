"""§13 数据自检 Warnings(高杠杆 / 商誉减值风险等)。"""

from __future__ import annotations


def build(ref, *, store, stock_index, indicators) -> str:
    warnings: list[str] = []
    try:
        rows = store.query_financial(ref.code, table="balance", years=1) or []
        last = rows[0] if rows else {}
        debt_ratio = last.get("DEBT_ASSET_RATIO") or 0
        if debt_ratio > 80:
            warnings.append("⚠️ 资产负债率 > 80%(高杠杆)")
        goodwill = last.get("GOODWILL") or 0
        equity = last.get("TOTAL_EQUITY") or 0
        if equity > 0 and goodwill > equity * 0.3:
            warnings.append("⚠️ 商誉 > 股东权益 30%(减值风险)")
    except Exception:  # noqa: BLE001
        pass
    if not warnings:
        return "## §13 数据自检 Warnings\n\n无显著异常\n"
    return "## §13 数据自检 Warnings\n\n" + "\n".join(f"- {w}" for w in warnings) + "\n"
