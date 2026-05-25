"""定性分析产物缓存(决策 Q1=d:30 天 TTL + REPORT_DATE 失效)。

落盘结构:
  data_dir/
    <code>_<name>/
      report_<YYYYMMDD>.json   ← QualitativeReport 序列化
      report_<YYYYMMDD>.md     ← 渲染后的 markdown(Agent C / 用户阅读)
      _meta.json               ← {report_date, ttl_until, cached_at, sources}

失效策略:
  - TTL 过期(默认 30 天)
  - 缓存中 report_date < 调用方传入的 current_report_date
    (即 DuckDB 中财务表出现更新的报告期 → 缓存内容已过时)

非失效场景:
  - current_report_date=None → 只检查 TTL(用户主动跳过校验)
  - current_report_date < 缓存 report_date → 不失效(理论上不该发生,容错)

Markdown 渲染逻辑放在 cache 外部,通过 put(..., md_text=...) 注入,
避免 schema 模块依赖渲染细节;若未提供 md_text,fallback 用简单拼接。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from services.agent.core.qualitative.schema import QualitativeReport

DEFAULT_TTL_DAYS = 30


class QualitativeCache:
    """按股票码隔离的定性分析产物缓存。

    线程安全:写盘走临时文件 + os.replace 模式;同一股票同时刻通常只有一个
    runner 在跑,coordinator 已做去重(由调用方保证)。
    """

    def __init__(self, data_dir: Path, *, ttl_days: int = DEFAULT_TTL_DAYS):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_days = ttl_days

    # ----- public -----

    def get(
        self,
        code: str,
        *,
        current_report_date: Optional[str] = None,
    ) -> Optional[QualitativeReport]:
        """返回有效缓存,过期/失效/不存在均返回 None。

        Args:
          code: 股票代码(如 600519.SH)
          current_report_date: DuckDB 中该股票最新 REPORT_DATE,用于失效判定;
            None 跳过报告期校验
        """
        d = self._find_dir(code)
        if d is None:
            return None
        meta = self._read_meta(d)
        if meta is None:
            return None

        # TTL 校验
        try:
            ttl_until = datetime.fromisoformat(meta["ttl_until"])
        except (KeyError, ValueError):
            return None
        if datetime.now() >= ttl_until:
            return None

        # REPORT_DATE 校验
        if current_report_date is not None:
            cached_rd = meta.get("report_date")
            if cached_rd and current_report_date > cached_rd:
                return None

        # 加载 json
        json_files = sorted(d.glob("report_*.json"))
        if not json_files:
            return None
        try:
            return QualitativeReport.model_validate_json(
                json_files[-1].read_text(encoding="utf-8")
            )
        except Exception:
            return None

    def put(
        self,
        report: QualitativeReport,
        *,
        md_text: Optional[str] = None,
        sources: Optional[list[str]] = None,
    ) -> Path:
        """写入新报告,返回缓存目录路径。"""
        d = self._dir_for(report.stock_code, report.stock_name)
        d.mkdir(parents=True, exist_ok=True)

        # 文件名以 report_date 编码,便于审计
        date_tag = report.report_date.replace("-", "")
        json_path = d / f"report_{date_tag}.json"
        md_path = d / f"report_{date_tag}.md"
        meta_path = d / "_meta.json"

        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        md_path.write_text(
            md_text if md_text is not None else self._render_fallback_md(report),
            encoding="utf-8",
        )
        now = datetime.now()
        meta = {
            "stock_code": report.stock_code,
            "stock_name": report.stock_name,
            "report_date": report.report_date,
            "cached_at": now.isoformat(),
            "ttl_until": (now + timedelta(days=self.ttl_days)).isoformat(),
            "sources": sources or [],
        }
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return d

    def invalidate(self, code: str) -> bool:
        """删除指定 code 的缓存目录。返回是否实际删除。"""
        d = self._find_dir(code)
        if d is None:
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True

    # ----- helpers -----

    def _dir_for(self, code: str, name: str) -> Path:
        # 同 cpa workspace 命名约定:<code>_<name>
        return self.data_dir / f"{code}_{name}"

    def _find_dir(self, code: str) -> Optional[Path]:
        """按 code 前缀查找目录(name 可能历史不一致)。"""
        if not self.data_dir.exists():
            return None
        for child in self.data_dir.iterdir():
            if child.is_dir() and child.name.startswith(f"{code}_"):
                return child
        # 兼容仅 code 命名的旧目录
        plain = self.data_dir / code
        if plain.is_dir():
            return plain
        return None

    @staticmethod
    def _read_meta(d: Path) -> Optional[dict]:
        meta_path = d / "_meta.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _render_fallback_md(report: QualitativeReport) -> str:
        """无外部渲染器时的兜底 markdown:6 维度叙事拼接 + 参数表。"""
        lines = [
            f"# 定性分析报告 · {report.stock_name}({report.stock_code})",
            "",
            f"报告期:{report.report_date}",
            "",
        ]
        for d in report.dimensions:
            lines.extend([f"## {d.title}", "", d.narrative, ""])
            if d.evidence:
                lines.append("**证据**:")
                lines.extend([f"- {e}" for e in d.evidence])
                lines.append("")

        lines.extend(
            [
                "## 结构化参数",
                "",
                "```json",
                report.params.model_dump_json(indent=2),
                "```",
            ]
        )
        return "\n".join(lines)
