"""§16 同业可比公司(期 1 占位 — 期 2 引入 stock_individual_info_em 行业元数据)。"""

from __future__ import annotations


def build(ref, **kw) -> str:
    return (
        "## §16 同业可比公司\n\n"
        "⚠️ 行业分类元数据缺失(期 2 引入 akshare stock_individual_info_em)\n"
    )
