"""§8 行业竞争与监管 — Tavily web search。

数据源:Tavily search API(行业景气 / 政策 / 竞争格局)
- 无 stock_index.industry → 降级文本(LLM 用先验)
- 无 tavily 注入或返回 None(无 key / 网络失败) → 降级文本
"""

from __future__ import annotations


def _query_for(industry: str, name: str) -> str:
    return f"{industry} 行业 政策 竞争格局 近6个月 {name}"


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
    industry = None
    if stock_index is not None:
        try:
            getter = getattr(stock_index, "get_industry", None)
            if callable(getter):
                industry = getter(ref.code)
        except Exception:  # noqa: BLE001
            industry = None

    if not industry:
        return (
            "## §8 行业竞争与监管\n\n"
            "> 数据待补 — 行业信息缺失,LLM 请基于先验给出谨慎判断,"
            "并明确标注「未经实时数据验证」。\n"
        )

    if tavily is None:
        return (
            "## §8 行业竞争与监管\n\n"
            f"- 所属行业:{industry}\n\n"
            "> 数据待补 — Tavily 未启用(未配置 TAVILY_API_KEY),"
            "LLM 请基于先验给出行业评估并标注「未经实时数据验证」。\n"
        )

    query = _query_for(industry, ref.name)
    payload = None
    try:
        payload = tavily.search_with_cache(ref.code, "industry", query)
    except Exception:  # noqa: BLE001
        payload = None

    if not payload:
        return (
            "## §8 行业竞争与监管\n\n"
            f"- 所属行业:{industry}\n\n"
            "> 数据待补 — Tavily 检索失败或无返回,LLM 请基于先验谨慎判断。\n"
        )

    answer = (payload.get("answer") or "").strip()
    results = payload.get("results") or []

    parts = [
        "## §8 行业竞争与监管",
        "",
        f"- 所属行业:**{industry}**",
        f"- 检索查询:`{query}`",
    ]
    if answer:
        parts += ["", f"### Tavily 摘要", "", answer]

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
        parts += ["", "> 检索结果为空。"]

    return "\n".join(parts) + "\n"
