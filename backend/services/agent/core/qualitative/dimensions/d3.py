"""D3 行业周期与定位 — 真实实现。

数据源:
- DuckDB v_a_income 近 5 年:TOTAL_OPERATE_INCOME / PARENT_NETPROFIT
  → 计算变异系数 CV (std/mean) 作为周期性量化信号
- Tavily search:行业景气度 / 周期阶段叙事(7 天文件缓存)

LLM 输出:
  cyclicality ∈ {强周期, 弱周期, 非周期}
  cycle_position ∈ {底部, 中段, 顶部}(仅 cyclicality=强周期 时填,否则强制清成 None)
  industry_keywords: list[str]

约束 / 降级:
- store 空 → ⚠️ 完全降级
- LLM None / 解析失败 / cyclicality 值域非法 → ⚠️
- cycle_position 值域非法 / 非强周期下出现 → 强制清成 None,整体不降级
- industry_keywords 非 list → 默认空列表
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "cyclicality": "弱周期",
    "cycle_position": None,
    "industry_keywords": [],
}

VALID_CYCLICALITY = ("强周期", "弱周期", "非周期")
VALID_POSITION = ("底部", "中段", "顶部")
YEARS = 5

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "d3.md"


def _market_of(code: str) -> str:
    upper = (code or "").upper()
    if upper.endswith((".SH", ".SZ")):
        return "a"
    if upper.endswith(".HK"):
        return "hk"
    return "us"


def _build_sql(market: str) -> str:
    return f"""
        SELECT
            REPORT_DATE,
            TOTAL_OPERATE_INCOME,
            PARENT_NETPROFIT
        FROM v_{market}_income
        WHERE _symbol = ?
          AND REPORT_DATE LIKE '%-12-31'
        ORDER BY REPORT_DATE DESC
        LIMIT {YEARS}
    """


def _compute_volatility(df: pd.DataFrame) -> Optional[dict[str, Any]]:
    """变异系数 CV = std / |mean|;mean=0 时跳过该列。"""
    if df is None or len(df) == 0:
        return None

    def _cv(col: str) -> Optional[float]:
        if col not in df.columns:
            return None
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) < 2:
            return None
        m = abs(s.mean())
        if m == 0:
            return None
        return float(s.std(ddof=0) / m)

    rev_cv = _cv("TOTAL_OPERATE_INCOME")
    profit_cv = _cv("PARENT_NETPROFIT")
    if rev_cv is None and profit_cv is None:
        return None
    return {
        "n_periods": len(df),
        "revenue_cv": rev_cv if rev_cv is not None else 0.0,
        "profit_cv": profit_cv if profit_cv is not None else 0.0,
    }


def _safe_tavily_search(tavily: Any, code: str, name: str) -> Optional[dict]:
    if tavily is None:
        return None
    try:
        return tavily.search_with_cache(
            code=code,
            section="d3_cycle",
            query=f"{name} 行业 周期 景气度 当前阶段",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D3 tavily search 异常 {code}: {e}")
        return None


def _format_tavily(payload: Optional[dict]) -> str:
    if not payload:
        return ""
    parts = []
    if payload.get("answer"):
        parts.append(f"### Tavily answer\n{payload['answer']}")
    results = payload.get("results") or []
    if results:
        parts.append("### Tavily results")
        for r in results[:5]:
            t = r.get("title", "")
            u = r.get("url", "")
            c = (r.get("content") or "")[:300]
            parts.append(f"- {t}({u}): {c}")
    return "\n".join(parts)


def _build_prompt(
    ref: StockRef, vol: dict[str, Any], tavily_payload: Optional[dict]
) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
    body = [
        f"# 输入:{ref.code} {ref.name}",
        "",
        f"## 近 {vol['n_periods']} 年波动率(CV = std/|mean|)",
        f"- 营收 CV:{vol['revenue_cv']:.4f}",
        f"- 归母净利 CV:{vol['profit_cv']:.4f}",
        "",
    ]
    tav = _format_tavily(tavily_payload)
    body.append(tav if tav else "(外部资讯不可用,仅基于波动率推断)")
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
        logger.debug(f"D3 LLM JSON 解析失败: {e}")
        return None


def _degrade(reason: str) -> tuple[DimensionReport, dict[str, Any]]:
    return (
        DimensionReport(
            name="D3",
            title="行业周期与定位",
            narrative=f"⚠️ {reason}",
            evidence=[],
        ),
        dict(DEFAULT_PARAMS),
    )


async def dimension_d3(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    **_: Any,
) -> tuple[DimensionReport, dict[str, Any]]:
    if store is None:
        return _degrade("D3 未注入 DuckDB store")

    try:
        df = store.query(_build_sql(_market_of(ref.code)), [ref.code])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D3 store.query 失败 {ref.code}: {e}")
        return _degrade(f"DuckDB 查询失败:{e}")

    vol = _compute_volatility(df)
    tavily_payload = _safe_tavily_search(tavily, ref.code, ref.name)

    if vol is None and not tavily_payload:
        return _degrade(f"{ref.code} 财务波动率与外部资讯均不可用")

    if llm is None:
        return _degrade("D3 未注入 LLM client")

    vol_for_prompt = vol or {"n_periods": 0, "revenue_cv": 0.0, "profit_cv": 0.0}
    prompt_text = _build_prompt(ref, vol_for_prompt, tavily_payload)

    from backend.services.system_config.llm_client import Message

    messages = [Message(role="user", content=prompt_text)]
    try:
        result = await llm.complete(messages)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D3 LLM 调用失败 {ref.code}: {e}")
        return _degrade(f"LLM 调用失败:{e}")

    parsed = _parse_llm_json(result.text or "")
    if not parsed:
        return _degrade("LLM 输出 JSON 解析失败,使用默认值")

    cyclicality = parsed.get("cyclicality")
    cycle_position = parsed.get("cycle_position")
    keywords = parsed.get("industry_keywords")
    narrative = parsed.get("narrative") or ""
    evidence = parsed.get("evidence") or []

    if cyclicality not in VALID_CYCLICALITY:
        logger.debug(f"D3 LLM cyclicality 值域非法 {cyclicality!r}")
        return _degrade(f"LLM cyclicality 值域非法 {cyclicality}")

    # 仅强周期时保留 cycle_position;否则强制清成 None
    if cyclicality != "强周期" or cycle_position not in VALID_POSITION:
        cycle_position = None

    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k) for k in keywords if k]

    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(e) for e in evidence]

    return (
        DimensionReport(
            name="D3",
            title="行业周期与定位",
            narrative=narrative or f"{ref.name} D3 评估完成。",
            evidence=evidence,
        ),
        {
            "cyclicality": cyclicality,
            "cycle_position": cycle_position,
            "industry_keywords": keywords,
        },
    )


# 兼容 Phase 1 占位名
mock_dimension_d3 = dimension_d3
