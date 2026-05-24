"""共享 markdown 表格 + 数字格式化工具。"""

from __future__ import annotations


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    h = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([h, sep, *body])


def fmt_million(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v) / 1e6:,.0f}"
    except (TypeError, ValueError):
        return "—"


def fmt_num(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"
