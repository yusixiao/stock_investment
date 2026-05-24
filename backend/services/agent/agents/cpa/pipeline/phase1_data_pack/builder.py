"""问股期 1 — DataPackBuilder:把 19 个 section 拼成 markdown 数据包。

每个 section 是 `build(ref, **deps) -> str | None` 函数。返回 None 表示
该 section 在当前市场不适用(由 builder 跳过)。

注册表 SECTION_REGISTRY 随后续 task 持续追加 §1/§2/§3/§3P/§4/§4P/§5/§6/
§9/§11/§12/§13/§15/§17 等 section。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import (
    s01_basic,
    s02_market,
    s03_income,
    s03p_parent_income,
    s04_balance,
    s04p_parent_balance,
    s05_cashflow,
    s06_dividend,
    s07_holders_placeholder,
    s08_industry_placeholder,
    s09_segments,
    s10_esg_placeholder,
    s11_weekly_kline,
    s12_ratios,
    s13_warnings,
    s14_rf,
    s15_industry_valuation,
    s16_peers_placeholder,
    s17_derived,
)
from services.agent.core.symbol import StockRef

SECTION_REGISTRY: dict = {
    "s01": s01_basic.build,
    "s02": s02_market.build,
    "s03": s03_income.build,
    "s03p": s03p_parent_income.build,
    "s04": s04_balance.build,
    "s04p": s04p_parent_balance.build,
    "s05": s05_cashflow.build,
    "s06": s06_dividend.build,
    "s07": s07_holders_placeholder.build,
    "s08": s08_industry_placeholder.build,
    "s09": s09_segments.build,
    "s10": s10_esg_placeholder.build,
    "s11": s11_weekly_kline.build,
    "s12": s12_ratios.build,
    "s13": s13_warnings.build,
    "s14": s14_rf.build,
    "s15": s15_industry_valuation.build,
    "s16": s16_peers_placeholder.build,
    "s17": s17_derived.build,
}

DEFAULT_INCLUDE = (
    "s01",
    "s02",
    "s03",
    "s03p",
    "s04",
    "s04p",
    "s05",
    "s06",
    "s07",
    "s08",
    "s09",
    "s10",
    "s11",
    "s12",
    "s13",
    "s14",
    "s15",
    "s16",
    "s17",
)


class DataPackBuilder:
    """把启用的 section 串成单文件 markdown 数据包。"""

    def __init__(
        self,
        *,
        store,
        stock_index,
        indicators,
        include: Iterable[str] = DEFAULT_INCLUDE,
    ):
        self.store = store
        self.stock_index = stock_index
        self.indicators = indicators
        self.include = tuple(include)

    def build(self, ref: StockRef, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        parts: list[str] = [f"# 数据包 — {ref.name}({ref.code})\n"]
        deps = dict(
            store=self.store,
            stock_index=self.stock_index,
            indicators=self.indicators,
        )
        for key in self.include:
            fn = SECTION_REGISTRY.get(key)
            if fn is None:
                continue
            chunk = fn(ref, **deps)
            if chunk is None:
                continue
            parts.append(chunk)
        out = output_dir / "data_pack_market.md"
        out.write_text("\n\n".join(parts), encoding="utf-8")
        return out
