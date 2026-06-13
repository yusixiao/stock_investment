"""前复权因子异常审计 — 检测并剔除 yfinance "幻灵拆股" 事件。

背景(2026-06,01211.HK 比亚迪事故):
    yfinance 的 `t.splits` 偶尔返回真实股价中并不存在的拆股事件。
    `fetch_adjust_factor` 盲信这些事件,把 factor_change=1/ratio 累乘进
    foreAdjustFactor,导致 qfq 价凭空跳变(BYD 2025 假涨 +1910%),
    污染所有 HK qfq 回测的绝对收益。

判据(数据驱动,可区分真假):
    真实的拆股/合股/大额分红,**必然**在 raw 日线 close 上留下对应跳空,
    即 factor_change ≈ raw_close[ex] / raw_close[prev]。
    幻灵事件 factor 突变但 raw 价平稳 → 二者在对数空间显著不一致 → 判为 phantom。

本模块只做纯数据计算(无 I/O),便于单测;DuckDB/parquet 接线在
scripts/clean_hk_adjust_factor.py 中。
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# 只审计"拆股级"的大变动:|ln(change)| > SPLIT_GATE(~15% 调整)。
# 低于此门槛的普通分红(change≈0.95~0.99)噪声大且非事故来源,一律保留。
SPLIT_GATE = 0.14
# raw 价跳空与 factor_change 在对数空间的最大容差。
# ln(1.5)≈0.405:允许除权日 ±50% 的市场波动/时点错配,
# 但 3:1(discrepancy≈3)/6:1(≈6)幻灵拆股远超此值。
MISMATCH_TOL = 0.405


@dataclass
class FactorEvent:
    """单条复权因子事件的审计结果。"""

    date: str
    factor: float  # 原始累积 foreAdjustFactor
    change: float  # 反推的单事件 factor_change(首事件=1.0,无前序)
    raw_ratio: Optional[float]  # raw close[ex]/close[prev];无法校验时 None
    is_phantom: bool
    reason: str


def _raw_ratio(
    date: str,
    raw_dates: Sequence[str],
    raw_closes: Sequence[float],
) -> Optional[float]:
    """计算除权日 raw 价跳空比 = first_close(>=date) / last_close(<date)。

    用跨日 (prev<date, next>=date) 而非精确等值,以兼容 ex-date 落在非交易日
    的情况(跳空会出现在下一交易日)。任一侧缺失 → None(无法校验)。
    """
    # last index with raw_dates[i] < date
    lo = bisect.bisect_left(raw_dates, date)
    if lo == 0:
        return None  # 没有更早的价格
    prev_close = raw_closes[lo - 1]
    # first index with raw_dates[i] >= date
    if lo >= len(raw_dates):
        return None  # 没有 >=date 的价格
    next_close = raw_closes[lo]
    if prev_close is None or next_close is None or prev_close <= 0 or next_close <= 0:
        return None
    return next_close / prev_close


def audit_factors(
    records: Sequence[Tuple[str, float]],
    raw: Sequence[Tuple[str, float]],
    *,
    split_gate: float = SPLIT_GATE,
    mismatch_tol: float = MISMATCH_TOL,
) -> List[FactorEvent]:
    """审计一只股票的复权因子序列,标记幻灵事件。

    参数:
        records: 升序 (dividOperateDate, foreAdjustFactor) 列表。
        raw:     升序 (date, close) raw 日线收盘价列表。
    返回:
        与 records 等长的 FactorEvent 列表(升序)。
    """
    events: List[FactorEvent] = []
    n = len(records)
    if n == 0:
        return events

    raw_dates = [d for d, _ in raw]
    raw_closes = [c for _, c in raw]

    for i, (date, factor) in enumerate(records):
        if i == 0:
            # 首事件没有前序累积值,无法反推单事件 change → 视为基准,保留。
            events.append(
                FactorEvent(date, factor, 1.0, None, False, "base (no prior event)")
            )
            continue

        prev_factor = records[i - 1][1]
        if factor <= 0 or prev_factor <= 0:
            events.append(
                FactorEvent(date, factor, 1.0, None, False, "non-positive factor")
            )
            continue

        # 单事件 factor_change:fore[i-1] = fore[i] * change_i  ⇒  change_i = fore[i-1]/fore[i]
        change = prev_factor / factor

        # 小变动(普通分红)直接放行,不校验。
        if abs(math.log(change)) <= split_gate:
            events.append(
                FactorEvent(date, factor, change, None, False, "small (dividend-level)")
            )
            continue

        ratio = _raw_ratio(date, raw_dates, raw_closes)
        if ratio is None:
            # 大变动但 raw 无法校验 → 保守保留(不误删未知合法事件)。
            events.append(
                FactorEvent(date, factor, change, None, False, "unverifiable (no raw)")
            )
            continue

        discrepancy = abs(math.log(change) - math.log(ratio))
        if discrepancy > mismatch_tol:
            events.append(
                FactorEvent(
                    date,
                    factor,
                    change,
                    ratio,
                    True,
                    f"phantom: change={change:.4f} but raw_ratio={ratio:.4f} "
                    f"(|Δln|={discrepancy:.2f}>{mismatch_tol})",
                )
            )
        else:
            events.append(
                FactorEvent(
                    date,
                    factor,
                    change,
                    ratio,
                    False,
                    f"corroborated: change={change:.4f}≈raw_ratio={ratio:.4f}",
                )
            )

    return events


def recompute_factors(events: Sequence[FactorEvent]) -> List[Tuple[str, float]]:
    """剔除幻灵事件(其 change 中性化为 1.0)后重算累积 foreAdjustFactor。

    锚点保持最新事件的原始因子(通常 1.0),从后往前重建:
        new_F[i] = new_F[i+1] * change'_{i+1}
    其中 change'_j = events[j].change(合法)或 1.0(幻灵)。
    返回升序 (date, foreAdjustFactor) 列表。
    """
    n = len(events)
    if n == 0:
        return []

    new_factors = [0.0] * n
    new_factors[n - 1] = events[n - 1].factor  # 锚点不动
    for i in range(n - 2, -1, -1):
        nxt = events[i + 1]
        eff_change = 1.0 if nxt.is_phantom else nxt.change
        new_factors[i] = new_factors[i + 1] * eff_change

    return [(events[i].date, round(new_factors[i], 6)) for i in range(n)]
