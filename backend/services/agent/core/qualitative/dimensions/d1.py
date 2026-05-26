"""D1 商业模式与资本特征 — 真实实现。

数据源:DuckDB 业务数据(纯本地,无外网)。
- v_a_balance: TOTAL_ASSETS / FIXED_ASSETS / GOODWILL / INTANGIBLE_ASSETS
              / ACCOUNTS_RECE / ADVANCE_RECEIVABLES
- v_a_cashflow: NETCASH_OPERATE / CONSTRUCT_LONG_ASSET (capex 代理)
- v_a_income:   TOTAL_OPERATE_INCOME

逻辑:
- 取近 3 年年报(REPORT_DATE 以 -12-31 结尾)
- 计算 5 个关键比率均值:
    asset_intensity = (FA+GW+IA) / TOTAL_ASSETS
    capex_ratio     = CONSTRUCT_LONG_ASSET / TOTAL_OPERATE_INCOME
    ar_ratio        = ACCOUNTS_RECE / TOTAL_OPERATE_INCOME
    ad_ratio        = ADVANCE_RECEIVABLES / TOTAL_OPERATE_INCOME
    ocf_ratio       = NETCASH_OPERATE / TOTAL_OPERATE_INCOME
- LLM 拍 (capital_intensity, collection_mode) 并产 narrative + evidence

Schema 值域:
- capital_intensity ∈ {capital-light, capital-hungry}
- collection_mode   ∈ {先款后货, 订阅预收, 先货后款, 垫资回收}

港股/美股市场视图(v_hk_*, v_us_*)缺字段时返回空 → 降级。
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

DEFAULT_PARAMS = {
    "capital_intensity": "capital-light",
    "collection_mode": "先货后款",
}

VALID_INTENSITY = ("capital-light", "capital-hungry")
VALID_COLLECTION = ("先款后货", "订阅预收", "先货后款", "垫资回收")

YEARS = 3

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "d1.md"


def _market_of(code: str) -> str:
    upper = (code or "").upper()
    if upper.endswith((".SH", ".SZ")):
        return "a"
    if upper.endswith(".HK"):
        return "hk"
    return "us"


def _build_sql(market: str) -> str:
    """三视图 LEFT JOIN,按 REPORT_DATE 取近 N 年年报。"""
    return f"""
        SELECT
            b.REPORT_DATE,
            b.TOTAL_ASSETS,
            b.FIXED_ASSET     AS FIXED_ASSETS,
            b.GOODWILL,
            b.INTANGIBLE_ASSET AS INTANGIBLE_ASSETS,
            b.ACCOUNTS_RECE,
            b.ADVANCE_RECEIVABLES,
            c.NETCASH_OPERATE,
            c.CONSTRUCT_LONG_ASSET,
            i.TOTAL_OPERATE_INCOME
        FROM v_{market}_balance b
        LEFT JOIN v_{market}_cashflow c
          ON c._symbol = b._symbol AND c.REPORT_DATE = b.REPORT_DATE
        LEFT JOIN v_{market}_income i
          ON i._symbol = b._symbol AND i.REPORT_DATE = b.REPORT_DATE
        WHERE b._symbol = ?
          AND b.REPORT_DATE LIKE '%-12-31'
        ORDER BY b.REPORT_DATE DESC
        LIMIT {YEARS}
    """


def _to_float(v: Any, default: float = 0.0) -> float:
    """pd.NA / None / NaN / 字符串异常 → default;数值正常返回 float。"""
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_div(num: Any, den: Any) -> Optional[float]:
    try:
        if num is None or den is None:
            return None
        if pd.isna(num) or pd.isna(den):
            return None
        n = float(num)
        d = float(den)
        if d == 0:
            return None
        return n / d
    except (TypeError, ValueError):
        return None


def _compute_ratios(df: pd.DataFrame) -> Optional[dict[str, float]]:
    """计算 5 个均值比率。空 df / 全无效行 → None。"""
    if df is None or len(df) == 0:
        return None

    asset_int: list[float] = []
    capex_r: list[float] = []
    ar_r: list[float] = []
    ad_r: list[float] = []
    ocf_r: list[float] = []

    for _, row in df.iterrows():
        ta = _to_float(row.get("TOTAL_ASSETS"))
        rev = _to_float(row.get("TOTAL_OPERATE_INCOME"))
        # asset_intensity 不依赖 revenue
        if ta > 0:
            fa = _to_float(row.get("FIXED_ASSETS"))
            gw = _to_float(row.get("GOODWILL"))
            ia = _to_float(row.get("INTANGIBLE_ASSETS"))
            asset_int.append((fa + gw + ia) / ta)

        # 其余比率需要 revenue > 0
        if rev <= 0:
            continue
        rev_f = rev
        v = _safe_div(row.get("CONSTRUCT_LONG_ASSET"), rev_f)
        if v is not None:
            capex_r.append(v)
        v = _safe_div(row.get("ACCOUNTS_RECE"), rev_f)
        if v is not None:
            ar_r.append(v)
        v = _safe_div(row.get("ADVANCE_RECEIVABLES"), rev_f)
        if v is not None:
            ad_r.append(v)
        v = _safe_div(row.get("NETCASH_OPERATE"), rev_f)
        if v is not None:
            ocf_r.append(v)

    if not asset_int and not capex_r:
        return None

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return {
        "asset_intensity": _mean(asset_int),
        "capex_ratio": _mean(capex_r),
        "ar_ratio": _mean(ar_r),
        "ad_ratio": _mean(ad_r),
        "ocf_ratio": _mean(ocf_r),
    }


def _build_prompt(ref: StockRef, ratios: dict[str, float]) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
    body = (
        f"# 输入:{ref.code} {ref.name} 近 {YEARS} 年年报均值\n\n"
        f"- asset_intensity(资产强度,固+商+无 占总资产):{ratios['asset_intensity']:.4f}\n"
        f"- capex_ratio(资本开支/营收):{ratios['capex_ratio']:.4f}\n"
        f"- ar_ratio(应收/营收):{ratios['ar_ratio']:.4f}\n"
        f"- ad_ratio(预收/营收):{ratios['ad_ratio']:.4f}\n"
        f"- ocf_ratio(经营现金流/营收):{ratios['ocf_ratio']:.4f}\n"
    )
    return template + "\n\n" + body if template else body


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
        logger.debug(f"D1 LLM JSON 解析失败: {e}")
        return None


def _degrade(reason: str) -> tuple[DimensionReport, dict[str, Any]]:
    return (
        DimensionReport(
            name="D1",
            title="商业模式与资本特征",
            narrative=f"⚠️ {reason}",
            evidence=[],
        ),
        dict(DEFAULT_PARAMS),
    )


async def dimension_d1(
    ref: StockRef,
    *,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    **_: Any,
) -> tuple[DimensionReport, dict[str, Any]]:
    """D1 真实维度执行函数。"""
    if store is None:
        return _degrade("D1 未注入 DuckDB store")

    market = _market_of(ref.code)
    sql = _build_sql(market)

    try:
        df = store.query(sql, [ref.code])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D1 store.query 失败 {ref.code}: {exc}")
        return _degrade(f"DuckDB 查询失败:{exc}")

    try:
        ratios = _compute_ratios(df)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D1 _compute_ratios 异常 {ref.code}: {exc}")
        return _degrade(f"比率计算异常:{exc}")
    if ratios is None:
        return _degrade(f"{ref.code} 财务数据不足,无法计算资本/收款比率")

    if llm is None:
        return _degrade("D1 未注入 LLM client")

    prompt_text = _build_prompt(ref, ratios)

    from backend.services.system_config.llm_client import Message

    messages = [Message(role="user", content=prompt_text)]

    try:
        result = await llm.complete(messages)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"D1 LLM 调用失败 {ref.code}: {exc}")
        return _degrade(f"LLM 调用失败:{exc}")

    parsed = _parse_llm_json(result.text or "")
    if not parsed:
        return _degrade("LLM 输出 JSON 解析失败,使用中性默认值")

    ci = parsed.get("capital_intensity")
    cm = parsed.get("collection_mode")
    narrative = parsed.get("narrative") or ""
    evidence = parsed.get("evidence") or []

    if ci not in VALID_INTENSITY or cm not in VALID_COLLECTION:
        logger.debug(f"D1 LLM 值域非法 ci={ci} cm={cm}")
        return _degrade(f"LLM 输出值域非法 ci={ci} cm={cm}")

    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    evidence = [str(e) for e in evidence]

    return (
        DimensionReport(
            name="D1",
            title="商业模式与资本特征",
            narrative=narrative or f"{ref.name} D1 评估完成。",
            evidence=evidence,
        ),
        {"capital_intensity": ci, "collection_mode": cm},
    )


# 兼容 Phase 1 占位名(runner / __init__ 仍用旧名时透明上线)
mock_dimension_d1 = dimension_d1
