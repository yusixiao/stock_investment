"""§14 无风险利率 Rf(2026Q2 中国 10Y 国债收益率快照)。"""

from __future__ import annotations

RF_CHINA_10Y = 0.027  # 2026Q2 快照,后续接 akshare bond_china_yield


def build(ref, **kw) -> str:
    return (
        "## §14 无风险利率 Rf\n\n"
        f"- 中国 10 年期国债收益率:**{RF_CHINA_10Y * 100:.2f}%**(常量,2026Q2 快照)\n"
    )
