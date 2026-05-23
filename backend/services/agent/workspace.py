"""Workspace 目录管理:每只股票独立目录 + _meta.json 原子读写。

目录结构:
    <root>/<code>_<name>/
        _meta.json          # 阶段状态、prompt hash 等
        *.md / *.json       # artifacts(分析报告等)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from services.agent.symbol import StockRef

# Windows / *nix 文件系统都不允许的字符
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, s: str) -> str:
        return _UNSAFE.sub("_", s).strip() or "_"

    def resolve_dir(self, ref: StockRef) -> Path:
        return self.root / f"{self._safe(ref.code)}_{self._safe(ref.name)}"

    def ensure(self, ref: StockRef) -> Path:
        d = self.resolve_dir(ref)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def read_meta(self, d: Path) -> dict:
        f = d / "_meta.json"
        if not f.exists():
            return {}
        return json.loads(f.read_text(encoding="utf-8"))

    def write_meta(self, d: Path, meta: dict) -> None:
        # 原子写:tmp 文件 + replace,避免半写状态
        tmp = d / "_meta.json.tmp"
        tmp.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(d / "_meta.json")

    def mark_phase(
        self,
        d: Path,
        phase: str,
        *,
        status: str,
        duration: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> None:
        meta = self.read_meta(d)
        meta.setdefault("phases", {})
        entry: dict = {"status": status}
        if duration is not None:
            entry["duration"] = duration
        if reason is not None:
            entry["reason"] = reason
        meta["phases"][phase] = entry
        self.write_meta(d, meta)

    def phase_status(self, d: Path, phase: str) -> Optional[str]:
        return self.read_meta(d).get("phases", {}).get(phase, {}).get("status")

    def relpath_for_artifact(self, d: Path, artifact: Path) -> str:
        return f"{d.name}/{artifact.name}"
