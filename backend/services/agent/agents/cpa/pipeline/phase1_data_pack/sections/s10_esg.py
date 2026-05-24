"""§10 ESG 与争议事件 — Tavily web search。

数据源:Tavily search API(近 12 个月处罚 / 诉讼 / 事故 / 环保)
- 无 tavily 注入或返回 None → 降级文本
- 检索结果空 → 明确告知「未检索到负面事件」(避免误读为「无 ESG 风险」)
"""

from __future__ import annotations


def _query_for(name: str) -> str:
    return f'"{name}" 处罚 OR 诉讼 OR 事故 OR 环保 OR 召回 近12个月'


def _truncate(s: str, n: int = 300) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n].rstrip() + "..."


def build(
    ref,
    *,
    store=None,
    stock_index=None,
    indicators=None,
    tavily=None,
    **_,
) -> str:
    if tavily is None:
        return (
            "## §10 ESG 与争议事件\n\n"
            "> 数据待补 — Tavily 未启用(未配置 TAVILY_API_KEY),"
            "LLM 请基于先验提示 ESG 风险并明确标注「未检索到实时争议事件」。\n"
        )

    query = _query_for(ref.name)
    payload = None
    try:
        payload = tavily.search_with_cache(ref.code, "esg", query)
    except Exception:  # noqa: BLE001
        payload = None

    if not payload:
        return "## §10 ESG 与争议事件\n\n> 数据待补 — Tavily 检索失败或无返回。\n"

    answer = (payload.get("answer") or "").strip()
    results = payload.get("results") or []

    parts = [
        "## §10 ESG 与争议事件",
        "",
        f"- 检索查询:`{query}`",
    ]
    if answer:
        parts += ["", "### Tavily 摘要", "", answer]

    if results:
        parts += ["", "### 检索结果(Top 5)", ""]
        for i, r in enumerate(results[:5], 1):
            title = (r.get("title") or "").strip() or "—"
            content = _truncate(r.get("content") or r.get("snippet") or "", 300)
            url = r.get("url") or ""
            parts.append(f"**[{i}] {title}**")
            if content:
                parts.append(content)
            if url:
                parts.append(f"<{url}>")
            parts.append("")
    else:
        parts += [
            "",
            "> 未检索到近 12 个月负面事件(请注意:仅基于公开网页检索,不能完全排除潜在风险)。",
        ]

    return "\n".join(parts) + "\n"
