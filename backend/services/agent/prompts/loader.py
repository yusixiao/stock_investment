"""Turtle prompts 加载器:支持 {var} 占位替换 + include 展开。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent / "turtle"


def _read(rel: str) -> str:
    path = PROMPTS_DIR / rel
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {rel}")
    return path.read_text(encoding="utf-8")


_INCLUDE_RE = re.compile(r"`references/([\w_]+\.md)`")


def load(name: str, *, expand_includes: bool = False, **vars: Any) -> str:
    """读取 prompt 并替换 {key} 占位。

    Args:
        name: prompt 相对路径(如 "phase3_quantitative.md")
        expand_includes: 把 `references/xxx.md` 反引用展开为内联 <ref> 块
        **vars: 占位变量,如 output_dir="/tmp/run_xyz"
    """
    text = _read(name)
    for key, val in vars.items():
        text = text.replace("{" + key + "}", str(val))
    if expand_includes:
        seen: set[str] = set()
        appendix: list[str] = []
        for m in _INCLUDE_RE.finditer(text):
            ref = m.group(1)
            if ref in seen:
                continue
            seen.add(ref)
            try:
                ref_text = _read(f"references/{ref}")
            except FileNotFoundError:
                continue
            appendix.append(
                f"\n\n<!-- expanded: references/{ref} -->\n"
                f"<ref name={ref}>\n{ref_text}\n</ref>\n"
            )
        text += "".join(appendix)
    return text
