"""§14 无风险利率 Rf。

优先 akshare `bond_china_yield` 取最新 10Y 国债收益率;
任何异常(超时 / 字段缺失 / 网络断)一律降级到 RF_CHINA_10Y 常量。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 2026Q2 快照,作为 akshare 不可达时的 fallback
RF_CHINA_10Y = 0.027


def _fetch_china_10y_yield() -> Optional[float]:
    """拉取中国 10Y 国债收益率(小数,如 0.0293)。失败返回 None,不抛。"""
    try:
        import akshare as ak

        df = ak.bond_china_yield(start_date="20260101", end_date="20261231")
        if df is None or len(df) == 0:
            return None
        # akshare 字段名历史多变,做兼容查找
        candidates = [
            "中国国债收益率10年",
            "10年",
            "yield_10y",
        ]
        col = next((c for c in candidates if c in df.columns), None)
        if col is None:
            return None
        latest = df.iloc[-1][col]
        if latest is None:
            return None
        # akshare 一般返回百分比数(2.93 表示 2.93%),转成小数
        val = float(latest)
        return val / 100.0 if val > 1 else val
    except Exception as e:
        logger.debug("§14 akshare bond_china_yield 失败,降级常量: %s", e)
        return None


def build(ref, **kw) -> str:
    rate = _fetch_china_10y_yield()
    if rate is not None:
        return (
            "## §14 无风险利率 Rf\n\n"
            f"- 中国 10 年期国债收益率:**{rate * 100:.2f}%**(akshare 实时)\n"
        )
    return (
        "## §14 无风险利率 Rf\n\n"
        f"- 中国 10 年期国债收益率:**{RF_CHINA_10Y * 100:.2f}%**(常量快照,降级)\n"
    )
