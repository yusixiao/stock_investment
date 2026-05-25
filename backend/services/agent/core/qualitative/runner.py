"""定性分析 runner — 编排 6 维度执行 + 缓存集成 + 流式事件。

设计要点(对齐 plan_business_analysis_agent.md Q3=c / Q4=d):
  - 外部 SSE 流式事件通过 on_event 注入(BA agent 实况展示)
  - 内部 6 维度函数顺序串行执行,各自负责调 Tavily/LLM
  - 失败容忍:某维度抛异常 → narrative 标 ⚠️,其他维度照跑
  - 缓存命中:跳过所有维度执行,直接返回(cpa Phase 0 加速场景)
  - on_event=None:静默运行(cpa Phase 0 内部调用,不污染外层 SSE)

事件契约:
  cache_hit       {type, code, report_date}
  dimension_start {type, name, title}
  dimension_done  {type, name, title}
  dimension_failed{type, name, title, error}

dimension_fns 协议:
  async def fn(ref, *, store, tavily, llm) -> tuple[DimensionReport, dict[str, Any]]
  返回 (该维度叙事报告, 该维度贡献的 params 部分字段)
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from services.agent.core.qualitative.cache import QualitativeCache
from services.agent.core.qualitative.schema import (
    DimensionReport,
    QualitativeParams,
    QualitativeReport,
)
from services.agent.core.symbol import StockRef

# 6 维度执行顺序 + 默认标题(若 dimension_fns 未提供则用这里的标题)
DIMENSION_ORDER: list[tuple[str, str]] = [
    ("D1", "商业模式与资本特征"),
    ("D2", "护城河与竞争格局"),
    ("D3", "行业周期与定位"),
    ("D4", "管理层与治理"),
    ("D5", "MD&A 可信度与导向"),
    ("D6", "控股结构与 SOTP"),
]

OnEvent = Optional[Callable[[dict[str, Any]], Awaitable[None]]]
DimensionFn = Callable[..., Awaitable[tuple[DimensionReport, dict[str, Any]]]]


async def _emit(on_event: OnEvent, event: dict[str, Any]) -> None:
    if on_event is not None:
        await on_event(event)


async def run_qualitative(
    ref: StockRef,
    *,
    cache: QualitativeCache,
    dimension_fns: dict[str, DimensionFn],
    current_report_date: Optional[str],
    on_event: OnEvent = None,
    store: Any = None,
    tavily: Any = None,
    llm: Any = None,
    force_refresh: bool = False,
    params_fallback: Optional[QualitativeParams] = None,
) -> QualitativeReport:
    """运行 6 维度定性分析,返回完整报告。

    Args:
      ref: 股票引用(code/name/market)
      cache: 缓存实例(get/put)
      dimension_fns: D1..D6 的异步函数映射
      current_report_date: DuckDB 中最新 REPORT_DATE,用于缓存失效判定
      on_event: 流式事件回调(可选,None 表示静默)
      store/tavily/llm: 透传给维度函数的依赖
      force_refresh: True 时跳过缓存读取
      params_fallback: 当 6 维度合并 params 不完整时的兜底(测试/降级场景)
    """
    # ----- 缓存命中快路径 -----
    if not force_refresh:
        cached = cache.get(ref.code, current_report_date=current_report_date)
        if cached is not None:
            await _emit(
                on_event,
                {
                    "type": "cache_hit",
                    "code": ref.code,
                    "report_date": cached.report_date,
                },
            )
            return cached

    # ----- 顺序执行 6 维度 -----
    dimensions: list[DimensionReport] = []
    merged_params: dict[str, Any] = {}

    for name, default_title in DIMENSION_ORDER:
        fn = dimension_fns.get(name)
        title = default_title
        await _emit(on_event, {"type": "dimension_start", "name": name, "title": title})

        if fn is None:
            # 未注册维度函数:降级为占位
            dimensions.append(
                DimensionReport(
                    name=name,
                    title=title,
                    narrative=f"⚠️ {name} 未注册维度函数",
                    evidence=[],
                )
            )
            await _emit(
                on_event,
                {
                    "type": "dimension_failed",
                    "name": name,
                    "title": title,
                    "error": "missing dimension function",
                },
            )
            continue

        try:
            dim, partial = await fn(ref, store=store, tavily=tavily, llm=llm)
            dimensions.append(dim)
            if partial:
                merged_params.update(partial)
            await _emit(
                on_event,
                {"type": "dimension_done", "name": name, "title": dim.title},
            )
        except Exception as exc:  # noqa: BLE001 — 故意宽容,容错降级
            dimensions.append(
                DimensionReport(
                    name=name,
                    title=title,
                    narrative=f"⚠️ {name} 执行失败:{exc}",
                    evidence=[],
                )
            )
            await _emit(
                on_event,
                {
                    "type": "dimension_failed",
                    "name": name,
                    "title": title,
                    "error": str(exc),
                },
            )

    # ----- 组装 params:优先用 6 维度合并结果,不完整时回退 fallback -----
    params = _build_params(merged_params, fallback=params_fallback)

    # ----- 用 current_report_date(若有)否则 unknown 作为报告期 -----
    report_date = current_report_date or "unknown"

    report = QualitativeReport(
        stock_code=ref.code,
        stock_name=ref.name,
        report_date=report_date,
        dimensions=dimensions,
        params=params,
    )

    # ----- 写缓存 -----
    cache.put(report)
    return report


def _build_params(
    merged: dict[str, Any],
    *,
    fallback: Optional[QualitativeParams],
) -> QualitativeParams:
    """6 维度 partials 合并 → QualitativeParams;不完整时用 fallback 兜底。

    校验失败(必填字段缺失)走 fallback;若 fallback 也 None 则抛 ValidationError
    (此时调用方代码有 bug,应在测试里就暴露)。
    """
    if merged:
        try:
            return QualitativeParams.model_validate(merged)
        except Exception:
            if fallback is not None:
                return fallback
            raise
    if fallback is not None:
        return fallback
    # 兜底失败:直接验证空 dict 让 pydantic 报详细错误
    return QualitativeParams.model_validate(merged)
