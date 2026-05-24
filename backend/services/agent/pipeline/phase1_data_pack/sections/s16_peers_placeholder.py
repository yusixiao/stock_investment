"""§16 同业可比公司 — 真实实现。

- 通过 stock_index 解析当前股票的行业(证监会分类),并定位同行
- 对当前股 + 同行各调一次 store.query_financial(table='indicator', years=1) 取最近一期关键比率
- 拼成 markdown 对比表(ROE / 毛利率 / 净利率 / 资产负债率)
- 任何缺失环节(无行业 / 无同行 / store 异常)优雅降级到说明文本

文件名保留 _placeholder 后缀以兼容 builder.SECTION_REGISTRY,后续整理时可重命名。
"""

from __future__ import annotations

from typing import Optional

from services.agent.pipeline.phase1_data_pack.sections._table import fmt_num, md_table

# 与 §12 一致,但只取最近一期
PEER_RATIO_FIELDS = [
    ("ROEJQ", "ROE(%)"),
    ("GROSSPROFIT_MARGIN", "毛利率(%)"),
    ("NETPROFIT_MARGIN", "净利率(%)"),
    ("DEBT_ASSET_RATIO", "资产负债率(%)"),
]


def _latest_indicator(store, code: str) -> Optional[dict]:
    """取最近一期 indicator;失败返回 None,不抛。"""
    try:
        rows = store.query_financial_for_section(code, table="indicator", years=1)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(rows, list) or not rows:
        return None
    try:
        rows = sorted(rows, key=lambda r: r.get("REPORT_DATE", ""), reverse=True)
        return rows[0] if rows else None
    except Exception:  # noqa: BLE001
        return None


def build(ref, *, store, stock_index, indicators=None, **kw) -> str:
    industry = None
    try:
        getter = getattr(stock_index, "get_industry", None)
        if callable(getter):
            industry = getter(ref.code)
    except Exception:  # noqa: BLE001
        industry = None

    if not industry:
        return (
            "## §16 同业可比公司\n\n"
            "> 行业分类缺失,无法定位同行(stock_index 未提供 industry)。\n"
        )

    # 找同行
    try:
        peers = stock_index.get_peers_by_industry(
            industry, exclude_code=ref.code, limit=5
        )
    except Exception:  # noqa: BLE001
        peers = []

    if not peers:
        return (
            f"## §16 同业可比公司\n\n- 所属行业:**{industry}**\n- 未找到同行(0 家)。\n"
        )

    # 当前股 + 同行,各取最近一期 indicator
    self_row = _latest_indicator(store, ref.code)
    peer_rows = [(p, _latest_indicator(store, p.code)) for p in peers]

    headers = ["公司", "代码"] + [label for _, label in PEER_RATIO_FIELDS]
    table_rows = []
    # 当前股第一行
    table_rows.append(
        [f"**{ref.name or ref.code}**", ref.code]
        + [fmt_num((self_row or {}).get(key), 2) for key, _ in PEER_RATIO_FIELDS]
    )
    for peer, row in peer_rows:
        name = getattr(peer, "name", None) or peer.code
        table_rows.append(
            [name, peer.code]
            + [fmt_num((row or {}).get(key), 2) for key, _ in PEER_RATIO_FIELDS]
        )

    return (
        f"## §16 同业可比公司\n\n"
        f"- 所属行业:**{industry}**(同行 {len(peers)} 家,按代码字典序前 5)\n\n"
        + md_table(headers, table_rows)
        + "\n"
    )
