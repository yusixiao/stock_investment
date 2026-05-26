"""D4 管理层与治理 — 真实实现。

数据源(2026-05-26 spike 验证):
- A 股:EastMoneyAdapter.fetch_company_management → emweb F10 PageAjax
- HK / US:YFinanceAdapter.fetch_company_management → companyOfficers + insider_transactions
- Tavily(可选):治理事件 / 高管变动新闻(7 天文件缓存,无 key 优雅降级)

派生量(prompt 输入):
- 核心高管:position 含 `董事长 / 总经理 / 副总经理 / 财务 / CFO / 董秘` 关键词
- 平均任期:从 tenure_text 解析起始年(A 股有,HK/US 缺则跳过)
- 近 12 月持股变动:净额 + 增持/减持笔数 + 大额事件
- Tavily 治理摘要

LLM JSON schema:
  { "management_rating": "优秀|合格|损害价值|观察期",
    "narrative": "...",
    "evidence": ["..."] }

降级:数据全空 / LLM 失败 / 值域非法 → ⚠️ 默认 "观察期"。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from services.agent.core.qualitative.schema import DimensionReport
from services.agent.core.symbol import StockRef

logger = logging.getLogger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {"management_rating": "观察期"}

VALID_RATING = ("优秀", "合格", "损害价值", "观察期")

# 核心高管识别关键词(中英文混合,匹配 position 字段)
CORE_KEYWORDS = (
    "董事长",
    "总经理",
    "副总经理",
    "财务",
    "CFO",
    "董秘",
    "Chief Executive",
    "CEO",
    "President",
    "Chief Financial",
)

CHANGE_WINDOW_DAYS = 365  # 近 12 个月

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "d4.md"


def _market_of(code: str) -> str:
    upper = (code or "").upper()
    if upper.endswith((".SH", ".SZ", ".BJ")):
        return "a"
    if upper.endswith(".HK"):
        return "hk"
    return "us"


def _is_core(position: Optional[str]) -> bool:
    if not position:
        return False
    return any(k in position for k in CORE_KEYWORDS)


_TENURE_RE = re.compile(r"(\d{4})")


def _parse_tenure_years(
    text: Optional[str], today: Optional[date] = None
) -> Optional[float]:
    """从 'YYYY-MM-DD至今' 之类文本提取首个 4 位年份,与今年差为任期(年)。"""
    if not text:
        return None
    m = _TENURE_RE.search(text)
    if not m:
        return None
    try:
        start_year = int(m.group(1))
    except ValueError:
        return None
    now = today or date.today()
    years = now.year - start_year
    if years < 0 or years > 60:
        return None
    return float(years)


def _avg_tenure(executives: list) -> Optional[float]:
    vals = [
        v
        for v in (
            _parse_tenure_years(getattr(e, "tenure_text", None)) for e in executives
        )
        if v is not None
    ]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def _within_window(d: str, today: Optional[date] = None) -> bool:
    try:
        dd = datetime.strptime(d[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    cutoff = (today or date.today()) - timedelta(days=CHANGE_WINDOW_DAYS)
    return dd >= cutoff


def _summarize_changes(changes: list, today: Optional[date] = None) -> dict[str, Any]:
    """近 12 月持股变动汇总。"""
    recent = [c for c in changes if _within_window(c.end_date, today)]
    n_increase = sum(1 for c in recent if c.change_num > 0)
    n_decrease = sum(1 for c in recent if c.change_num < 0)
    net = sum(c.change_num for c in recent)
    big_lots = [
        c
        for c in recent
        if (c.trade_way and ("大宗" in c.trade_way or "block" in c.trade_way.lower()))
    ]
    # top 3 by |change_num|
    top = sorted(recent, key=lambda c: abs(c.change_num), reverse=True)[:3]
    return {
        "n_total": len(recent),
        "n_increase": n_increase,
        "n_decrease": n_decrease,
        "net": net,
        "n_block": len(big_lots),
        "top": top,
    }


def _safe_tavily_search(tavily: Any, code: str, name: str) -> Optional[dict]:
    if tavily is None:
        return None
    try:
        return tavily.search_with_cache(
            code=code,
            section="d4_management",
            query=f"{name} 高管变动 处罚 关联交易 监管问询",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"D4 tavily search 异常 {code}: {e}")
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


def _format_executives(execs: list, max_n: int = 10) -> str:
    if not execs:
        return "(无高管列表)"
    lines = []
    for e in execs[:max_n]:
        bits = [e.name]
        if e.position:
            bits.append(e.position)
        if e.age is not None:
            bits.append(f"{e.age}岁")
        if e.education:
            bits.append(e.education)
        if e.tenure_text:
            bits.append(e.tenure_text)
        lines.append("- " + " | ".join(bits))
    return "\n".join(lines)


def _format_changes(summary: dict[str, Any]) -> str:
    if summary["n_total"] == 0:
        return "(近 12 月无持股变动记录)"
    lines = [
        f"- 近 12 月共 {summary['n_total']} 笔(增持 {summary['n_increase']} / 减持 {summary['n_decrease']})",
        f"- 净额:{summary['net']:+,.0f} 股",
    ]
    if summary["n_block"]:
        lines.append(f"- 大宗交易 {summary['n_block']} 笔")
    for c in summary["top"]:
        sign = "+" if c.change_num > 0 else ""
        price = f" @ {c.average_price:.2f}" if c.average_price is not None else ""
        relation = f"({c.executive_relation})" if c.executive_relation else ""
        lines.append(
            f"- {c.end_date} {c.executive_name}{relation} {c.position or ''} "
            f"{sign}{c.change_num:,.0f} 股{price}"
            + (f" [{c.trade_way}]" if c.trade_way else "")
        )
    return "\n".join(lines)


def _build_prompt(
    ref: StockRef,
    core_execs: list,
    all_execs: list,
    avg_tenure: Optional[float],
    change_summary: dict[str, Any],
    tavily_payload: Optional[dict],
) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
    body = [
        f"# 输入:{ref.code} {ref.name}",
        "",
        f"## 核心高管({len(core_execs)} / 共 {len(all_execs)} 人)",
        _format_executives(core_execs),
    ]
    if avg_tenure is not None:
        body.append(f"\n核心高管平均任期:**{avg_tenure} 年**")
    else:
        body.append("\n(任期数据不足,跳过该项指标)")

    body.append("\n## 近 12 月内部人持股变动")
    body.append(_format_changes(change_summary))

    tav = _format_tavily(tavily_payload)
    body.append("\n## 治理事件(Tavily)")
    body.append(tav or "(外部资讯不可用,未纳入治理事件)")

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
        logger.debug(f"D4 LLM JSON 解析失败: {e}")
        return None


def _degrade(reason: str) -> tuple[DimensionReport, dict[str, Any]]:
    return (
        DimensionReport(
            name="D4",
            title="管理层与治理",
            narrative=f"⚠️ {reason}",
            evidence=[],
        ),
        dict(DEFAULT_PARAMS),
    )


def _select_adapter(ref: StockRef, em_adapter: Any, yf_adapter: Any):
    """根据市场返回 (adapter, source_label)。"""
    market = _market_of(ref.code)
    if market == "a":
        if em_adapter is None:
            from backend.adapters.eastmoney_adapter import EastMoneyAdapter

            return EastMoneyAdapter(), "eastmoney"
        return em_adapter, "eastmoney"
    # HK / US
    if yf_adapter is None:
        from backend.adapters.yfinance_adapter import YFinanceAdapter

        return YFinanceAdapter(), "yfinance"
    return yf_adapter, "yfinance"


async def dimension_d4(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    em_adapter: Any = None,
    yf_adapter: Any = None,
    **_: Any,
) -> tuple[DimensionReport, dict[str, Any]]:
    """D4 真实维度执行函数。"""
    adapter, source = _select_adapter(ref, em_adapter, yf_adapter)

    try:
        executives, hold_changes = adapter.fetch_company_management(ref.code)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D4 fetch_company_management 失败 {ref.code}: {exc}")
        return _degrade(f"高管数据获取失败({source}):{exc}")

    core_execs = [e for e in (executives or []) if _is_core(e.position)]
    avg_tenure = _avg_tenure(core_execs) if source == "eastmoney" else None
    change_summary = _summarize_changes(hold_changes or [])

    tavily_payload = _safe_tavily_search(tavily, ref.code, ref.name)

    # 完全无数据:executives + 无变动 + 无 tavily → 降级到默认观察期
    if not executives and change_summary["n_total"] == 0 and not tavily_payload:
        return _degrade(f"{ref.code} 无高管 / 持股变动 / 治理事件数据,默认观察期")

    if llm is None:
        return _degrade("D4 未注入 LLM client")

    prompt_text = _build_prompt(
        ref,
        core_execs,
        executives or [],
        avg_tenure,
        change_summary,
        tavily_payload,
    )

    from backend.services.system_config.llm_client import Message

    messages = [Message(role="user", content=prompt_text)]

    try:
        result = await llm.complete(messages)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D4 LLM 调用失败 {ref.code}: {exc}")
        return _degrade(f"LLM 调用失败:{exc}")

    parsed = _parse_llm_json(result.text or "")
    if not parsed:
        return _degrade("LLM 输出 JSON 解析失败,使用默认观察期")

    rating = parsed.get("management_rating")
    narrative = parsed.get("narrative") or ""
    evidence = parsed.get("evidence") or []

    if rating not in VALID_RATING:
        logger.debug(f"D4 LLM 值域非法 rating={rating!r}")
        return _degrade(f"LLM 输出值域非法 rating={rating}")

    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(e) for e in evidence]

    return (
        DimensionReport(
            name="D4",
            title="管理层与治理",
            narrative=narrative or f"{ref.name} D4 评估完成。",
            evidence=evidence,
        ),
        {"management_rating": rating},
    )


# 兼容 Phase 1 占位名(runner/registry 仍以 mock_dimension_d4 引用)
mock_dimension_d4 = dimension_d4
