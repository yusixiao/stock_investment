"""Workspace 目录管理:每只股票独立目录,内部再分 work/(过程)与 report/(产物)。

目录结构(2026-06-15 拆分):
    <root>/<code>_<name>/
        report/                     # 最终产物(用户要的分析报告)
            <公司>_<代码>_分析报告.md
        work/                       # 可复用中间产物 + 状态机(可清理)
            _meta.json              # 阶段状态、duration、reason
            data_pack_market.md     # Phase1 数据包(确定性,可复用)
            phase3_quantitative.md  # Phase3.1 量化(LLM 产出,run 内复用)
            _quant_results.json     # 量化结果快照(调试用)

复用语义:跑流水线时 work/ 里已有的中间产物直接复用、跳过 LLM;缺失的才生成。
向后兼容:旧版本把文件平铺在 <code>_<name>/ 根目录,read_meta 会回退读取旧位置。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from services.agent.core.symbol import StockRef

# Windows / *nix 文件系统都不允许的字符
_UNSAFE = re.compile(r'[\\/:*?"<>|]')

# 子目录名
WORK_SUBDIR = "work"
REPORT_SUBDIR = "report"

# 中间产物文件名常量(供 pipeline 引用,消灭散落字面量)
META_NAME = "_meta.json"
DATA_PACK_NAME = "data_pack_market.md"
QUANT_MD_NAME = "phase3_quantitative.md"
QUANT_JSON_NAME = "_quant_results.json"


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
        # 同时建好 work/ 与 report/ 子目录
        (d / WORK_SUBDIR).mkdir(parents=True, exist_ok=True)
        (d / REPORT_SUBDIR).mkdir(parents=True, exist_ok=True)
        return d

    # ===== 子目录解析 =====

    def work_dir(self, d: Path) -> Path:
        """过程目录:中间产物 + 状态机。"""
        w = d / WORK_SUBDIR
        w.mkdir(parents=True, exist_ok=True)
        return w

    def report_dir(self, d: Path) -> Path:
        """产物目录:最终分析报告。"""
        r = d / REPORT_SUBDIR
        r.mkdir(parents=True, exist_ok=True)
        return r

    # ===== _meta.json 读写(落 work/)=====

    def _meta_path(self, d: Path) -> Path:
        return d / WORK_SUBDIR / META_NAME

    def read_meta(self, d: Path) -> dict:
        f = self._meta_path(d)
        if not f.exists():
            # 向后兼容:旧版本 _meta.json 平铺在 <code>_<name>/ 根目录
            legacy = d / META_NAME
            if legacy.exists():
                return json.loads(legacy.read_text(encoding="utf-8"))
            return {}
        return json.loads(f.read_text(encoding="utf-8"))

    def write_meta(self, d: Path, meta: dict) -> None:
        # 原子写:tmp 文件 + replace,避免半写状态
        w = d / WORK_SUBDIR
        w.mkdir(parents=True, exist_ok=True)
        tmp = w / (META_NAME + ".tmp")
        tmp.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(w / META_NAME)

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
        """产物相对路径,以 <root> 为基准(含 <code>_<name>/report/ 层级)。"""
        try:
            return f"{d.name}/{artifact.relative_to(d).as_posix()}"
        except ValueError:
            # artifact 不在 d 下(异常兜底),退化为仅文件名
            return f"{d.name}/{artifact.name}"
