"""Phase 3 量化报告解析器。

LLM 输出的报告末尾约定带 <results>...</results> 块,key=value 一行一对。
本模块负责把这些键值对解析为 dict,数值自动转 float,字符串保留。
"""

from __future__ import annotations

import re
from typing import Any

_BLOCK_RE = re.compile(r"<results>(.*?)</results>", re.DOTALL | re.IGNORECASE)
_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
_NUMERIC_CLEAN_RE = re.compile(r"[,%\s]")
_UNIT_TAIL_RE = re.compile(r"(百万|万元|亿元|元|股|倍|次)$")


def _coerce(val: str) -> Any:
    raw = val.strip()
    cleaned = _UNIT_TAIL_RE.sub("", raw).strip()
    cleaned = _NUMERIC_CLEAN_RE.sub("", cleaned)
    try:
        if "." in cleaned:
            return float(cleaned)
        return float(int(cleaned))
    except (ValueError, TypeError):
        return raw


def parse_phase3_quant_results(text: str) -> dict[str, Any]:
    """从 phase3_quantitative.md 提取 <results> 块。"""
    m = _BLOCK_RE.search(text)
    if not m:
        return {}
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        lm = _LINE_RE.match(line)
        if not lm:
            continue
        key, val = lm.group(1), lm.group(2)
        out[key] = _coerce(val)
    return out
