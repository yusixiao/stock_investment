"""D2 护城河与竞争格局 — 真实实现。

数据源:
- DuckDB v_a_indicator 近 5 年:ROEJQ / GROSSPROFIT_MARGIN(XSMLL) / NETPROFIT_MARGIN(XSJLL)
  → 长期高 ROE + 高毛利 = 护城河量化证据
- Tavily search:护城河叙事 + 主要竞争对手(7 天文件缓存,无 key 优雅降级)

LLM 输出:
  moat_type (str)
  moat_flywheel (bool)
  moat_rating ∈ {强, 较强, 中, 弱}
  competitors: [{name, ticker}]

降级规则:
- store 数据空 + tavily 也无内容 → 完全降级 ⚠️
- store 有数据、tavily 无 → 仅财务推断,不阻塞
- LLM None / 解析失败 / 值域非法 → ⚠️ 默认中性
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
    "moat_type": "未识别",
    "moat_flywheel": False,
    "moat_rating": "中",
    "competitors": [],
}

VALID_RATING = ("强", "较强", "中", "弱")
YEARS = 5

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "d2.md"


def _market_of(code: str) -> str:
    upper = (code or "").upper()
    if upper.endswith((".SH", ".SZ")):
        return "a"
    if upper.endswith(".HK"):
        return "hk"
    return "us"


def _build_sql(market: str) -> str:
    """近 5 年年报 indicator,字段映射成统一别名。"""
    return f"""
        SELECT
            REPORT_DATE,
            ROEJQ,
            XSMLL AS GROSSPROFIT_MARGIN,
            XSJLL AS NETPROFIT_MARGIN
        FROM v_{market}_indicator
        WHERE _symbol = ?
          AND REPORT_DATE LIKE '%-12-31'
        ORDER BY REPORT_DATE DESC
        LIMIT {YEARS}
    """


def _summarize_indicators(df: pd.DataFrame) -> Optional[dict[str, float]]:
    """返回近 5 年 ROE/毛利/净利的均值与样本量。"""
    if df is None or len(df) == 0:
        return None

    def _mean(col: str) -> Optional[float]:
        if col not in df.columns:
            return None
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        return float(s.mean()) if len(s) > 0 else None

    roe = _mean("ROEJQ")
    gpm = _mean("GROSSPROFIT_MARGIN")
    npm = _mean("NETPROFIT_MARGIN")
    if roe is None and gpm is None and npm is None:
        return None
    return {
        "n_periods": len(df),
        "roe_mean": roe or 0.0,
        "gpm_mean": gpm or 0.0,
        "npm_mean": npm or 0.0,
    }


def _safe_tavily_search(tavily: Any, code: str, name: str) -> Optional[dict]:
    """单次 search,异常 / 无 client 都返 None。"""
    if tavily is None:
        return None
    try:
        return tavily.search_with_cache(
            code=code,
            section="d2_moat",
            query=f"{name} 护城河 竞争优势 主要竞争对手",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D2 tavily search 异常 {code}: {e}")
        return None


def _format_tavily(payload: Optional[dict]) -> str:
    if not payload:
        return ""
    parts = []
    answer = payload.get("answer")
    if answer:
        parts.append(f"### Tavily answer\n{answer}")
    results = payload.get("results") or []
    if results:
        parts.append("### Tavily results")
        for r in results[:5]:
            title = r.get("title", "")
            url = r.get("url", "")
            content = (r.get("content") or "")[:300]
            parts.append(f"- {title}({url}): {content}")
    return "\n".join(parts)


def _build_prompt(
    ref: StockRef,
    metrics: dict[str, float],
    tavily_payload: Optional[dict],
) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
    body = [
        f"# 输入:{ref.code} {ref.name}",
        "",
        f"## 近 {metrics['n_periods']} 年财务均值",
        f"- ROEJQ:{metrics['roe_mean']:.2f}%",
        f"- 毛利率:{metrics['gpm_mean']:.2f}%",
        f"- 净利率:{metrics['npm_mean']:.2f}%",
        "",
    ]
    tav = _format_tavily(tavily_payload)
    if tav:
        body.append(tav)
    else:
        body.append("(外部资讯不可用,仅基于财务指标推断)")
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
        logger.debug(f"D2 LLM JSON 解析失败: {e}")
        return None


def _sanitize_competitors(raw: Any) -> list[dict[str, str]]:
    """只保留 dict 且 name+ticker 都非空的项。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        ticker = item.get("ticker")
        if not name or not ticker:
            continue
        out.append({"name": str(name), "ticker": str(ticker)})
    return out


def _degrade(reason: str) -> tuple[DimensionReport, dict[str, Any]]:
    return (
        DimensionReport(
            name="D2",
            title="护城河与竞争格局",
            narrative=f"⚠️ {reason}",
            evidence=[],
        ),
        dict(DEFAULT_PARAMS),
    )


async def dimension_d2(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    **_: Any,
) -> tuple[DimensionReport, dict[str, Any]]:
    """D2 真实维度执行函数。"""
    metrics: Optional[dict[str, float]] = None
    if store is not None:
        try:
            df = store.query(_build_sql(_market_of(ref.code)), [ref.code])
            metrics = _summarize_indicators(df)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"D2 store.query 失败 {ref.code}: {e}")

    tavily_payload = _safe_tavily_search(tavily, ref.code, ref.name)

    if metrics is None and not tavily_payload:
        return _degrade(f"{ref.code} 财务指标与外部资讯均不可用")

    if llm is None:
        return _degrade("D2 未注入 LLM client")

    # 即便 metrics 缺失,只要 tavily 有内容也尝试推断;反之亦然
    metrics_for_prompt = metrics or {
        "n_periods": 0,
        "roe_mean": 0.0,
        "gpm_mean": 0.0,
        "npm_mean": 0.0,
    }
    prompt_text = _build_prompt(ref, metrics_for_prompt, tavily_payload)

    from backend.services.system_config.llm_client import Message

    messages = [Message(role="user", content=prompt_text)]

    try:
        result = await llm.complete(messages)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D2 LLM 调用失败 {ref.code}: {e}")
        return _degrade(f"LLM 调用失败:{e}")

    parsed = _parse_llm_json(result.text or "")
    if not parsed:
        return _degrade("LLM 输出 JSON 解析失败,使用中性默认值")

    moat_type = parsed.get("moat_type")
    moat_flywheel = parsed.get("moat_flywheel")
    moat_rating = parsed.get("moat_rating")
    narrative = parsed.get("narrative") or ""
    evidence = parsed.get("evidence") or []
    competitors = _sanitize_competitors(parsed.get("competitors"))

    if (
        not isinstance(moat_type, str)
        or not isinstance(moat_flywheel, bool)
        or moat_rating not in VALID_RATING
    ):
        logger.debug(
            f"D2 LLM 值域非法 type={moat_type!r} flywheel={moat_flywheel!r} rating={moat_rating!r}"
        )
        return _degrade(
            f"LLM 输出值域非法 type={moat_type} flywheel={moat_flywheel} rating={moat_rating}"
        )

    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(e) for e in evidence]

    return (
        DimensionReport(
            name="D2",
            title="护城河与竞争格局",
            narrative=narrative or f"{ref.name} D2 评估完成。",
            evidence=evidence,
        ),
        {
            "moat_type": moat_type,
            "moat_flywheel": moat_flywheel,
            "moat_rating": moat_rating,
            "competitors": competitors,
        },
    )


# 兼容 Phase 1 占位名
mock_dimension_d2 = dimension_d2
