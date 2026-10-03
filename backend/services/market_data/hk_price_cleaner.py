"""港股行情输入清洗。

Eastmoney/研究快照偶尔会出现单日价格放大后下一交易日恢复原尺度的坏 tick。
这种记录不是可交易的公司行为，应在历史导入和增量更新两条链路统一丢弃。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar


T = TypeVar("T")

_TRANSIENT_SCALE_THRESHOLD = 10.0
_NEIGHBOR_RETURN_TOLERANCE = 0.20


def _value(record: T, field: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(field)
    return getattr(record, field, None)


def _is_transient_scale_spike(previous: float, current: float, following: float) -> bool:
    if previous <= 0 or current <= 0 or following <= 0:
        return False

    prev_ratio = current / previous
    next_ratio = following / current
    scale_jump = max(prev_ratio, 1.0 / prev_ratio)
    scale_reversal = max(next_ratio, 1.0 / next_ratio)
    neighbor_ratio = following / previous

    return (
        scale_jump >= _TRANSIENT_SCALE_THRESHOLD
        and scale_reversal >= _TRANSIENT_SCALE_THRESHOLD
        and 1.0 - _NEIGHBOR_RETURN_TOLERANCE
        <= neighbor_ratio
        <= 1.0 + _NEIGHBOR_RETURN_TOLERANCE
    )


def clean_transient_scale_spikes(records: Sequence[T]) -> list[T]:
    """删除单日数量级放大后立即恢复的价格毛刺。

    只删除中间一根记录，持续性的价格尺度变化会被保留。输出保持输入顺序。
    无法解析日期或收盘价的记录不参与检测，也不被本函数删除。
    """
    if len(records) < 3:
        return list(records)

    indexed = []
    for index, record in enumerate(records):
        try:
            date = str(_value(record, "date"))[:10]
            close = float(_value(record, "close"))
        except (TypeError, ValueError):
            continue
        if not date or close <= 0:
            continue
        indexed.append((date, close, index))

    indexed.sort(key=lambda item: item[0])
    drop_indexes: set[int] = set()
    for previous, current, following in zip(indexed, indexed[1:], indexed[2:]):
        if _is_transient_scale_spike(
            previous[1], current[1], following[1]
        ):
            drop_indexes.add(current[2])

    kept = [item for item in indexed if item[2] not in drop_indexes]
    updated: dict[int, T] = {}
    previous_close: float | None = None
    for _, close, original_index in kept:
        record = records[original_index]
        if previous_close is not None:
            record = _update_derived_fields(record, previous_close, close)
        updated[original_index] = record
        previous_close = close

    return [
        updated.get(index, record)
        for index, record in enumerate(records)
        if index not in drop_indexes
    ]


def _update_derived_fields(record: T, previous_close: float, close: float) -> T:
    pct_change = (close - previous_close) / previous_close * 100
    if isinstance(record, Mapping):
        updated = dict(record)
        if "preclose" in updated:
            updated["preclose"] = previous_close
        if "pctChg" in updated:
            updated["pctChg"] = pct_change
        return updated  # type: ignore[return-value]

    fields = getattr(type(record), "model_fields", {})
    changes = {}
    if "preclose" in fields:
        changes["preclose"] = previous_close
    if "pctChg" in fields:
        changes["pctChg"] = pct_change
    model_copy = getattr(record, "model_copy", None)
    if changes and callable(model_copy):
        return model_copy(update=changes)  # type: ignore[return-value]
    return record
