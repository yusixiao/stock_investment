"""§16 同业可比公司 — Phase 1 占位。

Phase 2 实现计划:
- 前置:`stock_index` 暴露 `get_industry(code)`(读 baostock 已采集的 `StockBasic.industry`)
- 数据源:`DuckDBStore` 新增 `query_peers_by_industry(industry, limit=5)` 返回同行业市值前 N 标的
- 拼装:对每个 peer 调用现有 §12 ratios 逻辑,生成对比表(PE / PB / ROE / 毛利率)
- LLM 用途:Phase 3.2 估值阶段做相对估值锚定
"""

from __future__ import annotations


def build(ref, **kw) -> str:
    return (
        "## §16 同业可比公司\n\n"
        "> 数据待补(Phase 2)。当前 `stock_index` 未暴露行业字段,无法定位同行。\n\n"
        "**计划输出**:同行业市值前 5 标的的 PE / PB / ROE / 毛利率对比表,"
        "供 Phase 3.2 做相对估值锚定。\n"
    )
