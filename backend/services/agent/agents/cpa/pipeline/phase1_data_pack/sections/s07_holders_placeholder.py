"""§7 控股股东与管理层 — Phase 1 占位。

Phase 2 实现计划:
- 数据源:akshare `stock_gdfx_top_10_em`(前 10 流通股东)+ `stock_management_change_em`(高管变动)
- 落地:新建 `holders_updater` → DuckDB 视图 `v_a_holders` → `DuckDBStore.query_top10_holders(code)`
- LLM 用途:Phase 3.2 估值阶段判定股权结构稳定性、是否有大股东减持信号
"""

from __future__ import annotations


def build(ref, **kw) -> str:
    return (
        "## §7 控股股东与管理层\n\n"
        "> 数据待补(Phase 2)。LLM 在估值阶段如需引用股权结构,"
        "请基于公开信息谨慎给出结论,或注明「数据未提供」。\n\n"
        "**计划字段**:前 10 流通股东持股比例、控股股东、近 1 年高管变动、股权质押比例。\n"
    )
