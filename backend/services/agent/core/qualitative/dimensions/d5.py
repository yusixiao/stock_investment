"""D5 MD&A 可信度与导向 — 真实实现。

数据源:EastMoney F10 RPT_F10_OP_BUSINESSANALYSIS(28 期年报/中报/季报全文)。
2026-05-26 spike 验证(益丰药房 603939):年报 1.4-3.3k 字,结构化纯文本。

逻辑:
- 取最近 2 期年报(REPORT_NAME 含"年报")做"承诺 vs 兑现"对比
- 若仅 1 期:做单期披露质量评估
- 若 0 期(只有季报/中报):降级 ⚠️ + 中性默认值
- LLM 输出 JSON,JSON 解析失败 → 降级 ⚠️ + 中性默认值

LLM JSON schema:
  { "mda_credibility": "高|中|低",
    "mda_impact": "正面|中性|负面",
    "narrative": "...",
    "evidence": ["...", "..."] }

签名兼容 runner 的 `fn(ref, *, store, tavily, llm)`,额外接受 em_adapter 测试注入。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef

logger = logging.getLogger(__name__)

DEFAULT_PARAMS = {"mda_credibility": "中", "mda_impact": "中性"}

# 最多塞进 prompt 的最近年报数;多了浪费 token,2 期足够做"承诺 vs 兑现"
MAX_ANNUAL_REPORTS = 2

# 单份年报截断长度(字符);避免极少数公司年报过长
PER_REVIEW_CHAR_CAP = 4000

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "d5.md"


def _is_annual(report_name: Optional[str]) -> bool:
    return bool(report_name) and "年报" in report_name


def _filter_annual_reports(records: list) -> list:
    """筛出年报,records 已按 REPORT_DATE 降序(adapter 默认排序)。"""
    return [r for r in records if _is_annual(getattr(r, "REPORT_NAME", None))]


def _truncate(text: Optional[str], cap: int = PER_REVIEW_CHAR_CAP) -> str:
    if not text:
        return ""
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n...[已截断,原文共 {len(text)} 字]"


def _build_prompt_text(ref: StockRef, annuals: list) -> str:
    """组装 prompt:加载 d5.md 模板 + 拼接年报全文。"""
    template = _PROMPT_PATH.read_text(encoding="utf-8")

    parts = [
        f"# 输入:{ref.code} {ref.name} 历年经营评述",
        "",
    ]
    for r in annuals:
        parts.append(f"## {r.REPORT_NAME}({r.REPORT_DATE})")
        parts.append(_truncate(r.BUSINESS_REVIEW))
        parts.append("")

    return template + "\n\n" + "\n".join(parts)


def _parse_llm_json(text: str) -> Optional[dict[str, Any]]:
    """从 LLM 返回中提取 JSON 对象。

    容忍格式:
    - 裸 JSON `{...}`
    - ```json\n{...}\n``` 代码块
    - 带前后说明文字
    """
    if not text:
        return None

    # 优先匹配 ```json``` 代码块
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        # 退回找首个 { ... } 平衡块(贪婪从首 { 到末 })
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        candidate = m.group(0)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        logger.debug(f"D5 LLM JSON 解析失败: {e}")
        return None


def _degrade(reason: str) -> tuple[DimensionReport, dict[str, Any]]:
    return (
        DimensionReport(
            name="D5",
            title="MD&A 可信度与导向",
            narrative=f"⚠️ {reason}",
            evidence=[],
        ),
        dict(DEFAULT_PARAMS),
    )


async def dimension_d5(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    em_adapter: Any = None,
) -> tuple[DimensionReport, dict[str, Any]]:
    """D5 真实维度执行函数。"""
    adapter = em_adapter if em_adapter is not None else EastMoneyAdapter()

    try:
        all_records = adapter.fetch_business_review(ref.code)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D5 fetch_business_review 失败 {ref.code}: {exc}")
        return _degrade(f"经营评述数据获取失败:{exc}")

    annuals = _filter_annual_reports(all_records or [])

    if not annuals:
        return _degrade(f"{ref.code} 无可用年报经营评述(仅季报/中报或数据为空)")

    if llm is None:
        return _degrade("D5 未注入 LLM client")

    annuals_for_prompt = annuals[:MAX_ANNUAL_REPORTS]
    prompt_text = _build_prompt_text(ref, annuals_for_prompt)

    # 延迟 import 避免循环依赖
    from backend.services.system_config.llm_client import Message

    messages = [Message(role="user", content=prompt_text)]

    try:
        result = await llm.complete(messages)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D5 LLM 调用失败 {ref.code}: {exc}")
        return _degrade(f"LLM 调用失败:{exc}")

    parsed = _parse_llm_json(result.text or "")
    if not parsed:
        return _degrade("LLM 输出 JSON 解析失败,使用中性默认值")

    cred = parsed.get("mda_credibility")
    impact = parsed.get("mda_impact")
    narrative = parsed.get("narrative") or ""
    evidence = parsed.get("evidence") or []

    # 值域校验:落在 schema Literal 之外则降级
    if cred not in ("高", "中", "低") or impact not in ("正面", "中性", "负面"):
        logger.debug(f"D5 LLM 值域非法 cred={cred} impact={impact}")
        return _degrade(f"LLM 输出值域非法 cred={cred} impact={impact}")

    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(e) for e in evidence]

    return (
        DimensionReport(
            name="D5",
            title="MD&A 可信度与导向",
            narrative=narrative or f"{ref.name} D5 评估完成。",
            evidence=evidence,
        ),
        {"mda_credibility": cred, "mda_impact": impact},
    )


# 兼容 Phase 1 占位名(若 cpa Phase 0 / runner 注册时仍用旧名)
mock_dimension_d5 = dimension_d5
