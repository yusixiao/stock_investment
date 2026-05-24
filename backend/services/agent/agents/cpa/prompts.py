"""CPA agent prompts loader:绑定到 agents/cpa/prompts/ 目录。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.agent.core import prompts_loader as _core_loader

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load(name: str, *, expand_includes: bool = False, **vars: Any) -> str:
    """读取 CPA agent 的 prompt 并替换占位 / 展开 references。"""
    return _core_loader.load(PROMPTS_DIR, name, expand_includes=expand_includes, **vars)
