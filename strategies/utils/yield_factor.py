"""股息率因子 utils。

定义:`TTM 股息率 = sum(过去 12 个月除权日落在当前日期前的 cash_dividend) / 当前价`。

A 股 cash_dividend 单位 = 元/股(税前)。dividend 表 `date` 字段是除权日,语义稳健。
若无分红记录,返 0(明确"零派息",而非 None,便于参与排序)。

性能优化(memoize):
- 输出依赖 (symbol, date),无法跨日期缓存
- 但 cash_dividend 序列本身不变,可在 df.attrs 上缓存预处理后的 (years, cash_per_share)
- 单次 screen 调用 ~5500 只 × O(N_div) 复杂度,N_div 通常 ≤ 50,可接受
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def get_dividend_ttm_per_share(
    ctx, symbol: str, *, as_of: Optional[str] = None
) -> float:
    """过去 12 个月内除权日的 cash_dividend 累加(每股)。

    as_of 默认 = ctx.current_date。无分红记录返 0.0(零派息也是有效信号)。
    """
    if as_of is None:
        as_of = getattr(ctx, "current_date", None)
    cur = _parse_date(as_of) if as_of else None
    if cur is None:
        return 0.0
    df = ctx.get_dividend(symbol) if hasattr(ctx, "get_dividend") else None
    if df is None or len(df) == 0 or "cash_dividend" not in df.columns:
        return 0.0

    cash = pd.to_numeric(df["cash_dividend"], errors="coerce")
    mask = cash.notna() & (cash > 0)
    if not mask.any():
        return 0.0

    # 只看除权日在 (cur - 365d, cur] 区间内的
    dates = df.loc[mask, "date"].astype(str)
    cash_v = cash[mask]
    total = 0.0
    for ds, cv in zip(dates, cash_v, strict=False):
        d = _parse_date(ds)
        if d is None:
            continue
        delta = (cur - d).days
        if 0 <= delta <= 365:
            total += float(cv)
    return total


def get_dividend_yield_ttm(ctx, symbol: str) -> Optional[float]:
    """TTM 股息率 = TTM 每股现金分红 / 当前收盘价。

    无价格 → None;有股票但无分红记录 → 0.0(零派息也是有效因子值)。
    """
    div_per_share = get_dividend_ttm_per_share(ctx, symbol)
    # 取当前收盘价
    px = None
    if hasattr(ctx, "get_price"):
        row = ctx.get_price(symbol)
        if row is not None:
            # 兼容两种返回格式:{"close": x} 或 {"daily": {"close": x}}
            if "close" in row:
                px = row.get("close")
            elif "daily" in row and isinstance(row["daily"], dict):
                px = row["daily"].get("close")
    if px is None or px <= 0:
        return None
    return div_per_share / float(px)
