"""通用 prompts 加载器:支持 {var} 占位替换 + include 展开。

每个 agent 在自己的 `prompts.py` 中绑定 `PROMPTS_DIR` 调用本模块,
避免硬编码任何 agent 的目录路径。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_INCLUDE_RE = re.compile(r"`references/([\w_]+\.md)`")


def _read(prompts_dir: Path, rel: str) -> str:
    path = prompts_dir / rel
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {rel}")
    return path.read_text(encoding="utf-8")


def load(
    prompts_dir: Path,
    name: str,
    *,
    expand_includes: bool = False,
    **vars: Any,
) -> str:
    """读取 prompt 并替换 {key} 占位。

    Args:
        prompts_dir: 该 agent 的 prompts 根目录(由调用方传入)
        name: prompt 相对路径(如 "phase3_quantitative.md")
        expand_includes: 把 `references/xxx.md` 反引用展开为内联 <ref> 块
        **vars: 占位变量,如 output_dir="/tmp/run_xyz"
    """
    text = _read(prompts_dir, name)
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
                ref_text = _read(prompts_dir, f"references/{ref}")
            except FileNotFoundError:
                continue
            appendix.append(
                f"\n\n<!-- expanded: references/{ref} -->\n"
                f"<ref name={ref}>\n{ref_text}\n</ref>\n"
            )
        text += "".join(appendix)
    return text
