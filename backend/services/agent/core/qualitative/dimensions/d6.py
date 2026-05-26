"""D6 控股结构与 SOTP — 真实实现。

数据源:
- DuckDB store:query_top10_holders / query_top10_free_holders / query_holder_count
- Tavily(可选):子公司 / 业务板块 / 控股平台搜索

派生量(prompt 输入):
- 最新一期十大股东 + 集中度(top1 / top3 / top10 比例之和)
- 股东类型分布(法人 / 自然人 / 基金等,从 HOLDER_NAME 关键词推断)
- 股东户数最近期 + 较上期变动率
- Tavily 业务板块摘要

LLM JSON schema:
  {"holding_structure": bool,
   "sotp_discount_pct": float | null,
   "narrative": "...",
   "evidence": ["..."]}

降级:数据全空 / LLM 失败 / 值域非法 → ⚠️ 默认 holding_structure=False。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "holding_structure": False,
    "sotp_discount_pct": None,
}

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "d6.md"


def _safe_query(store: Any, method: str, *args, **kwargs) -> list[dict]:
    if store is None:
        return []
    fn = getattr(store, method, None)
    if fn is None:
        return []
    try:
        return list(fn(*args, **kwargs) or [])
    except Exception as e:  # noqa: BLE001
        logger.debug(f"D6 store.{method} 异常: {e}")
        return []


def _latest_period_rows(rows: list[dict]) -> tuple[str, list[dict]]:
    """从 list[dict] 取最新 END_DATE 的全部行,按 HOLDER_RANK 升序。"""
    if not rows:
        return "", []
    rows_sorted = sorted(rows, key=lambda r: str(r.get("END_DATE") or ""), reverse=True)
    latest = rows_sorted[0].get("END_DATE") or ""
    same = [r for r in rows_sorted if r.get("END_DATE") == latest]
    same.sort(key=lambda r: r.get("HOLDER_RANK") or 99)
    return str(latest), same[:10]


def _concentration(rows: list[dict], ratio_key: str) -> dict[str, float]:
    """计算 top1 / top3 / top10 持股比例之和。"""
    out = {"top1": 0.0, "top3": 0.0, "top10": 0.0}
    if not rows:
        return out
    ratios: list[float] = []
    for r in rows:
        v = r.get(ratio_key)
        if v is None:
            continue
        try:
            ratios.append(float(v))
        except (TypeError, ValueError):
            continue
    if ratios:
        out["top1"] = round(ratios[0], 2)
        out["top3"] = round(sum(ratios[:3]), 2)
        out["top10"] = round(sum(ratios[:10]), 2)
    return out


_HOLDER_KEYWORDS = {
    "国资": ("国资委", "国有资产", "国家"),
    "集团/控股": ("集团", "控股", "Holdings", "Holding", "Group"),
    "基金": ("基金", "投资基金", "Fund", "ETF"),
    "境外": ("HKSCC", "香港中央", "QFII"),
    "自然人": ("先生", "女士"),  # 粗略
}


def _classify_holders(rows: list[dict]) -> dict[str, int]:
    """股东类型粗分类(关键词命中,可重叠不计入多类)。"""
    counts = {k: 0 for k in _HOLDER_KEYWORDS}
    for r in rows:
        name = str(r.get("HOLDER_NAME") or "")
        for cat, kws in _HOLDER_KEYWORDS.items():
            if any(k in name for k in kws):
                counts[cat] += 1
                break  # 每行只算一类
    return counts


def _safe_tavily(tavily: Any, code: str, name: str) -> Optional[dict]:
    if tavily is None:
        return None
    try:
        return tavily.search_with_cache(
            code=code,
            section="d6_holding_structure",
            query=f"{name} 子公司 业务板块 控股平台 多元化",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D6 tavily 异常 {code}: {e}")
        return None


def _format_top10(period: str, rows: list[dict], ratio_key: str, title: str) -> str:
    if not rows:
        return f"### {title}\n(无数据)"
    lines = [f"### {title}(报告期 {period[:10] if period else '—'})"]
    for r in rows:
        rank = r.get("HOLDER_RANK") or "—"
        name = r.get("HOLDER_NAME") or "—"
        ratio = r.get(ratio_key)
        ratio_s = f"{float(ratio):.2f}%" if ratio is not None else "—"
        htype = r.get("HOLDER_TYPE") or ""
        state = r.get("HOLDER_STATEE") or r.get("HOLDER_STATE") or ""
        lines.append(f"- {rank}. {name} | {ratio_s} | {htype} | {state}".rstrip(" |"))
    return "\n".join(lines)


def _format_concentration(c10: dict, c10f: dict) -> str:
    return (
        "### 持股集中度\n"
        f"- 十大股东:top1 {c10['top1']}% | top3 {c10['top3']}% | top10 {c10['top10']}%\n"
        f"- 十大流通股东:top1 {c10f['top1']}% | top3 {c10f['top3']}% | top10 {c10f['top10']}%"
    )


def _format_holder_count(rows: list[dict]) -> str:
    if not rows:
        return "### 股东户数\n(无数据)"
    latest = rows[0]
    cur = latest.get("HOLDER_NUM")
    pre = latest.get("PRE_HOLDER_NUM")
    chg = latest.get("HOLDER_NUM_RATIO")
    parts = ["### 股东户数"]
    if cur is not None:
        parts.append(f"- 当期:{int(cur):,} 户")
    if pre is not None:
        parts.append(f"- 上期:{int(pre):,} 户")
    if chg is not None:
        parts.append(f"- 较上期变动:{float(chg):+.2f}%")
    return "\n".join(parts)


def _format_holder_classification(counts: dict[str, int]) -> str:
    if not any(counts.values()):
        return "### 股东类型分布\n(关键词未命中)"
    lines = ["### 股东类型分布(基于姓名关键词)"]
    for cat, n in counts.items():
        if n:
            lines.append(f"- {cat}:{n} 个")
    return "\n".join(lines)


def _format_tavily(payload: Optional[dict]) -> str:
    if not payload:
        return "### Tavily 业务板块检索\n(外部资讯不可用)"
    parts = ["### Tavily 业务板块检索"]
    answer = payload.get("answer")
    if answer:
        parts.append(f"**摘要**:{answer}")
    results = payload.get("results") or []
    for r in results[:5]:
        title = r.get("title", "")
        url = r.get("url", "")
        content = (r.get("content") or "")[:300]
        parts.append(f"- {title}({url}): {content}")
    return "\n".join(parts)


def _build_prompt(
    ref: StockRef,
    period_top10: str,
    top10: list[dict],
    period_top10f: str,
    top10_free: list[dict],
    holder_count: list[dict],
    concentration: dict[str, float],
    concentration_free: dict[str, float],
    holder_types: dict[str, int],
    tavily_payload: Optional[dict],
) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
    body = [
        f"# 输入:{ref.code} {ref.name}",
        "",
        _format_top10(period_top10, top10, "HOLD_NUM_RATIO", "十大股东"),
        "",
        _format_top10(period_top10f, top10_free, "FREE_HOLDNUM_RATIO", "十大流通股东"),
        "",
        _format_concentration(concentration, concentration_free),
        "",
        _format_holder_classification(holder_types),
        "",
        _format_holder_count(holder_count),
        "",
        _format_tavily(tavily_payload),
    ]
    return (template + "\n\n" if template else "") + "\n".join(body)


def _parse_llm_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        candidate = m.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.debug(f"D6 LLM JSON 解析失败: {e}")
        return None


def _degrade(reason: str) -> tuple[DimensionReport, dict[str, Any]]:
    return (
        DimensionReport(
            name="D6",
            title="控股结构与 SOTP",
            narrative=f"⚠️ {reason}",
            evidence=[],
        ),
        dict(DEFAULT_PARAMS),
    )


async def dimension_d6(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    **_: Any,
) -> tuple[DimensionReport, dict[str, Any]]:
    """D6 真实维度执行函数。"""
    top10_all = _safe_query(store, "query_top10_holders", ref.code, latest_n_periods=1)
    top10_free_all = _safe_query(
        store, "query_top10_free_holders", ref.code, latest_n_periods=1
    )
    holder_count = _safe_query(store, "query_holder_count", ref.code)

    period_top10, top10 = _latest_period_rows(top10_all)
    period_top10f, top10_free = _latest_period_rows(top10_free_all)

    tavily_payload = _safe_tavily(tavily, ref.code, ref.name)

    # 完全无数据:股东三表 + Tavily 全空 → 降级
    if not top10 and not top10_free and not holder_count and not tavily_payload:
        return _degrade(f"{ref.code} 无股东数据与外部资讯,默认非控股结构")

    if llm is None:
        return _degrade("D6 未注入 LLM client")

    concentration = _concentration(top10, "HOLD_NUM_RATIO")
    concentration_free = _concentration(top10_free, "FREE_HOLDNUM_RATIO")
    holder_types = _classify_holders(top10)

    prompt_text = _build_prompt(
        ref,
        period_top10,
        top10,
        period_top10f,
        top10_free,
        holder_count,
        concentration,
        concentration_free,
        holder_types,
        tavily_payload,
    )

    from backend.services.system_config.llm_client import Message

    messages = [Message(role="user", content=prompt_text)]

    try:
        result = await llm.complete(messages)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D6 LLM 调用失败 {ref.code}: {exc}")
        return _degrade(f"LLM 调用失败:{exc}")

    parsed = _parse_llm_json(result.text or "")
    if not parsed:
        return _degrade("LLM 输出 JSON 解析失败")

    holding_structure = parsed.get("holding_structure")
    sotp = parsed.get("sotp_discount_pct")
    narrative = parsed.get("narrative") or ""
    evidence = parsed.get("evidence") or []

    if not isinstance(holding_structure, bool):
        return _degrade(f"holding_structure 非 bool:{holding_structure!r}")

    # sotp_discount_pct 校验
    if holding_structure:
        if sotp is None:
            return _degrade("holding_structure=True 但 sotp_discount_pct 缺失")
        try:
            sotp_v = float(sotp)
        except (TypeError, ValueError):
            return _degrade(f"sotp_discount_pct 非数值:{sotp!r}")
        if not (0.0 <= sotp_v <= 1.0):
            return _degrade(f"sotp_discount_pct 越界:{sotp_v}")
        sotp_final: Optional[float] = round(sotp_v, 4)
    else:
        # 强制 False 时为 None,无视 LLM 给的非 null 值
        sotp_final = None

    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(e) for e in evidence]

    return (
        DimensionReport(
            name="D6",
            title="控股结构与 SOTP",
            narrative=narrative or f"{ref.name} D6 评估完成。",
            evidence=evidence,
        ),
        {
            "holding_structure": holding_structure,
            "sotp_discount_pct": sotp_final,
        },
    )


# 兼容 Phase 1 占位名(runner/registry 仍以 mock_dimension_d6 引用)
mock_dimension_d6 = dimension_d6
