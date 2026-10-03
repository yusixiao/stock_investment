"""港股分红前复权因子计算共享逻辑。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def build_dividend_factor_rows(
    dividend_events: Iterable[tuple[str, float]],
    close_map: Mapping[str, float],
) -> list[tuple[str, float]]:
    """按分红事件构建前复权因子，并补齐历史起点基准。

    因子记录不仅要覆盖除权日，还要在首个除权日前提供一个基准值；否则
    DuckDB ASOF JOIN 会在首个事件前 COALESCE 到 1.0，造成首个事件人工跳变。
    返回值按日期升序，最后一个事件的因子固定为 1.0。
    """
    dates = sorted(str(date)[:10] for date in close_map)
    if not dates:
        return []

    close_by_date = {str(date)[:10]: float(close) for date, close in close_map.items()}
    events: list[tuple[str, float]] = []
    for event_date, amount in dividend_events:
        ex_date = str(event_date)[:10]
        try:
            dividend = float(amount)
        except (TypeError, ValueError):
            continue
        if dividend <= 0:
            continue

        previous_dates = [date for date in dates if date < ex_date]
        if not previous_dates:
            continue
        previous_close = close_by_date[max(previous_dates)]
        if previous_close <= 0:
            continue

        factor_change = (previous_close - dividend) / previous_close
        if factor_change <= 0 or factor_change > 1:
            continue
        events.append((ex_date, factor_change))

    if not events:
        return []

    merged: dict[str, float] = {}
    for event_date, factor_change in events:
        merged[event_date] = merged.get(event_date, 1.0) * factor_change
    events = sorted(merged.items())

    factors = [0.0] * len(events)
    factors[-1] = 1.0
    for index in range(len(events) - 2, -1, -1):
        factors[index] = factors[index + 1] * events[index + 1][1]

    rows: list[tuple[str, float]] = []
    history_start = dates[0]
    first_event_date, first_change = events[0]
    if history_start < first_event_date:
        # 首个事件之前的价格也必须使用“包含首个事件”的历史基准因子。
        rows.append((history_start, round(factors[0] * first_change, 6)))

    rows.extend(
        (event_date, round(factor, 6))
        for (event_date, _), factor in zip(events, factors)
    )
    return rows
