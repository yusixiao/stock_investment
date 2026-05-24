"""§14 无风险利率 Rf。

使用常量快照(2026-05-24:移除 akshare 依赖,akshare 在本环境不稳定)。
后续可在年度更新时手动维护 RF_CHINA_10Y 值,或接入 baostock / eastmoney
的债券收益率端点(待评估)。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 中国 10Y 国债收益率快照(2026Q2)。手动维护,避免对 akshare 的运行时依赖。
RF_CHINA_10Y = 0.027


def build(ref, **kw) -> str:
    return (
        "## §14 无风险利率 Rf\n\n"
        f"- 中国 10 年期国债收益率:**{RF_CHINA_10Y * 100:.2f}%**(常量快照)\n"
    )
