"""保守分析 agent manifest — r1 T20-T31 实施期间的占位 manifest。"""

MANIFEST = {
    "id": "cpa_conservative",
    "label": "保守分析",
    "aliases": ["保守分析", "现金流保守策略", "保守", "cpa", "穿透回报率"],
    "description": "基于 CPA 视角的极端保守假设穿透回报率精算,适合长期持有决策。",
    "version": "1.0.0",
    "steps": [
        {"id": "data_pack", "label": "拉取数据包", "estimated_seconds": 30},
        {"id": "quant", "label": "量化分析(穿透回报率)", "estimated_seconds": 180},
        {"id": "valuation", "label": "估值与报告组装", "estimated_seconds": 120},
    ],
    "requires": [
        "llm.chat",
        "data.duckdb.daily",
        "data.duckdb.financial",
        "data.duckdb.dividend",
        "data.duckdb.valuation",
    ],
    "enabled": True,
}
