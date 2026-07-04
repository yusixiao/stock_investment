from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar, Union

import pandas as pd
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

KeyType = Union[str, List[str], tuple]


def read_parquet_as_models(
    path: Path, model_class: Type[T], sort_by: str = "date", ascending: bool = False
) -> List[T]:
    """读取 parquet 文件并转换为 Pydantic 模型列表"""
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    if df.empty:
        return []
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
    records = df.where(df.notna(), None).to_dict("records")
    return [model_class.model_validate(r) for r in records]


def write_models_as_parquet(
    path: Path,
    records: List[T],
    sort_by: str = "date",
    ascending: bool = False,
    *,
    integrity: Optional[IntegrityPolicy] = None,
) -> None:
    """将 Pydantic 模型列表写入 parquet 文件。

    integrity 非 None 时, 落盘前运行数据完整性护栏(A档「禁销毁」), 检测到
    「用坏数据覆盖好数据」raise DataIntegrityError。默认 None=关闭(向后兼容,
    既有调用点行为不变)。"""
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    dicts = [r.model_dump(exclude_none=False) for r in records]
    df = pd.DataFrame(dicts)
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
    if integrity is not None:
        check_write_integrity(
            path,
            df,
            key=integrity.key,
            mode=integrity.mode,
            force=integrity.force,
            row_drop_ratio=integrity.row_drop_ratio,
            record_dir=integrity.record_dir,
        )
    df.to_parquet(path, index=False)


def append_models_to_parquet(
    path: Path,
    new_records: List[T],
    model_class: Type[T],
    dedup_key="date",
    sort_by: str = "date",
    ascending: bool = False,
    *,
    integrity: Optional[IntegrityPolicy] = None,
) -> None:
    """增量追加记录到 parquet 文件，按 dedup_key 去重。

    dedup_key 支持单字段 str(向后兼容)或复合键 tuple/list:
        dedup_key="REPORT_DATE"               # 单键
        dedup_key=("END_DATE", "HOLDER_RANK")  # 复合键(§7 多行/期场景)

    冲突策略: 新记录覆盖旧记录 — 重要,因为下游可能在盘中误抓 partial bar,
    收盘后需要被完整收盘数据覆盖。

    integrity 非 None 时透传给最终 write_models_as_parquet: 护栏比较「去重后全集
    vs 磁盘旧文件」, 保留行原样匹配(不误报), 新记录抹掉旧非空则拦截。"""
    if not new_records:
        return
    existing = read_parquet_as_models(path, model_class, sort_by=None)
    # new_records 在前: 同 key 时新记录先入 seen,后续 existing 同 key 会被丢弃
    all_records = list(new_records) + existing

    if isinstance(dedup_key, (tuple, list)):
        keys = tuple(dedup_key)

        def _key(r):
            return tuple(getattr(r, k) for k in keys)
    else:

        def _key(r):
            return getattr(r, dedup_key)

    seen = set()
    deduped = []
    for r in all_records:
        k = _key(r)
        if k not in seen:
            seen.add(k)
            deduped.append(r)
    write_models_as_parquet(
        path, deduped, sort_by=sort_by, ascending=ascending, integrity=integrity
    )


# ---------------------------------------------------------------------------
# 写入前数据完整性护栏 (A档「禁销毁」)
#
# 背景: 2026-07-02 一次财务重抓命中明细报表,INDUSTRY_NAME 整列变 null,静默
# 覆盖了磁盘上的好数据。本护栏在落盘前拦截「用坏数据覆盖好数据」的写入。
# ---------------------------------------------------------------------------


@dataclass
class IntegrityPolicy:
    """写入护栏声明(逐调用点显式指定, 不从 write_/append_ 自动推断)。

    key:  台账去重键(单键 str 或复合键 list/tuple), 用于逐行比对。
    mode: "ledger"(台账型, 查值销毁+结构) 或 "recompute"(重算型, 仅查结构)。
    force: True=明知违规也放行并留痕(财报重述等合法大变动)。
    """

    key: Optional[KeyType] = None
    mode: str = "ledger"
    force: bool = False
    row_drop_ratio: float = 0.5
    record_dir: Optional[Path] = None


@dataclass
class DataIntegrityViolation:
    """单条完整性违规。kind ∈ {value_nulled, column_dropped, row_count_drop}。"""

    kind: str
    path: str
    detail: str
    column: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "column": self.column,
            "detail": self.detail,
        }


class DataIntegrityError(RuntimeError):
    """写入前护栏检测到「销毁已有数据」风险,拒绝落盘 (fail-closed)。"""

    def __init__(self, violations: List[DataIntegrityViolation]):
        self.violations = violations
        detail = "; ".join(v.detail for v in violations)
        super().__init__(f"data integrity check failed: {detail}")


def _resolve_record_dir(record_dir: Optional[Path]) -> Path:
    """告警落地目录。默认 config.LOG_DIR(惰性导入以兼容双 import 风格)。"""
    if record_dir is not None:
        return Path(record_dir)
    try:
        from backend.config import LOG_DIR
    except ImportError:  # pytest pythonpath=. backend 场景
        from config import LOG_DIR
    return Path(LOG_DIR)


def _emit_alert(
    violations: List[DataIntegrityViolation],
    *,
    forced: bool,
    record_dir: Optional[Path] = None,
) -> None:
    """记录完整性违规: app 日志 + data_integrity.log(可读) + data_integrity.jsonl(可查)。

    forced=True 表示 force 逃生阀放行,仍留痕但不阻断。
    真推送(bark/飞书/邮件)后续在此扩展 —— 定时任务无人值守,持久化可查是底线。
    """
    prefix = "FORCED-THROUGH" if forced else "BLOCKED"
    for v in violations:
        logger.error("data integrity %s: %s", prefix, v.detail)

    try:
        rec_dir = _resolve_record_dir(record_dir)
        rec_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with (rec_dir / "data_integrity.log").open("a", encoding="utf-8") as f:
            for v in violations:
                f.write(f"{ts} [{prefix}] {v.kind} {v.path} :: {v.detail}\n")
        with (rec_dir / "data_integrity.jsonl").open("a", encoding="utf-8") as f:
            for v in violations:
                rec = v.to_dict()
                rec["ts"] = ts
                rec["forced"] = forced
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # 记录失败绝不能反过来阻断/掩盖主流程
        logger.warning("failed to persist data integrity record: %s", e)


def _key_of(rec: Dict, key: KeyType):
    if isinstance(key, (list, tuple)):
        return tuple(rec.get(k) for k in key)
    return rec.get(key)


def check_write_integrity(
    path: Path,
    new_df: pd.DataFrame,
    *,
    key: Optional[KeyType] = None,
    mode: str = "ledger",
    force: bool = False,
    row_drop_ratio: float = 0.5,
    record_dir: Optional[Path] = None,
) -> None:
    """落盘前数据完整性护栏 (A档「禁销毁」)。

    mode="ledger" (台账型: kline/财务/分红/股东/指数):
        - 已存在 key 的行,某列 旧非空 → 新 null = 违规(销毁数据)
        - 旧有列在新数据中整列消失 = 违规
        - 行数低于旧文件 row_drop_ratio 倍 = 违规(灾难性骤减)
        放行: 新增 key 行 / null→有值回填 / 非空→不同非空(盘中→收盘) / 同值。
    mode="recompute" (重算/快照型: 复权因子/股票列表/流通股/港股行业):
        历史值可合法重算,仅查 整列消失 + 行数骤减。

    检测到违规: _emit_alert 记录+告警, 然后 raise DataIntegrityError;
    force=True: 明知违规也放行(留痕), 用于财报重述等合法大变动。
    首次写/空基线/空新数据/旧文件不可读 → 放行(无基线可比)。
    """
    if new_df is None or len(new_df) == 0:
        return
    path = Path(path)
    if not path.exists():
        return
    try:
        old_df = pd.read_parquet(path)
    except Exception as e:
        logger.warning("integrity check skipped (cannot read existing %s): %s", path, e)
        return
    if old_df is None or len(old_df) == 0:
        return

    violations: List[DataIntegrityViolation] = []
    old_cols = set(old_df.columns)
    new_cols = set(new_df.columns)

    # 结构护栏(两种模式都查): 整列消失
    for col in sorted(old_cols - new_cols):
        violations.append(
            DataIntegrityViolation(
                kind="column_dropped",
                path=str(path),
                column=col,
                detail=(
                    f"column '{col}' present in existing data disappeared from new write"
                ),
            )
        )

    # 结构护栏(两种模式都查): 行数灾难性骤减
    if len(new_df) < len(old_df) * row_drop_ratio:
        violations.append(
            DataIntegrityViolation(
                kind="row_count_drop",
                path=str(path),
                detail=(
                    f"row count dropped {len(old_df)} -> {len(new_df)} "
                    f"(below {row_drop_ratio:.0%} of existing)"
                ),
            )
        )

    # 台账型专属: 已存在 key 上 非空→null 的销毁检测
    if mode == "ledger" and key is not None:
        key_cols = list(key) if isinstance(key, (list, tuple)) else [key]
        if all(c in old_cols and c in new_cols for c in key_cols):
            common_cols = [
                c for c in new_df.columns if c in old_cols and c not in key_cols
            ]
            old_index = {
                _key_of(rec, key): rec for rec in old_df.to_dict("records")
            }
            nulled_by_col: Dict[str, list] = {}
            for rec in new_df.to_dict("records"):
                old_rec = old_index.get(_key_of(rec, key))
                if old_rec is None:
                    continue  # 新 key = 新增,放行
                for c in common_cols:
                    if pd.notna(old_rec.get(c)) and pd.isna(rec.get(c)):
                        nulled_by_col.setdefault(c, []).append(_key_of(rec, key))
            for col, keys in nulled_by_col.items():
                sample = [str(k) for k in keys[:5]]
                violations.append(
                    DataIntegrityViolation(
                        kind="value_nulled",
                        path=str(path),
                        column=col,
                        detail=(
                            f"{len(keys)} existing row(s) had non-null '{col}' "
                            f"overwritten with null; sample keys={sample}"
                        ),
                    )
                )

    if not violations:
        return

    _emit_alert(violations, forced=force, record_dir=record_dir)
    if not force:
        raise DataIntegrityError(violations)


def read_integrity_violations(
    limit: int = 20,
    recent_hours: int = 24,
    record_dir: Optional[Path] = None,
) -> Dict:
    """读取完整性违规记录 (健康端点数据源, 读 data_integrity.jsonl)。

    返回: total(累计条数) / blocked(拒写) / forced(逃生放行) / recent_24h(近
    recent_hours 小时内条数, 用于判定 degraded) / latest_ts / recent(最近 limit 条)。
    文件不存在或不可读 → 全 0(不抛)。
    """
    result: Dict = {
        "total": 0,
        "blocked": 0,
        "forced": 0,
        "recent_24h": 0,
        "latest_ts": None,
        "recent": [],
    }
    jsonl = _resolve_record_dir(record_dir) / "data_integrity.jsonl"
    if not jsonl.exists():
        return result
    try:
        lines = jsonl.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning("failed to read integrity records: %s", e)
        return result

    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    cutoff = datetime.now(timezone.utc) - timedelta(hours=recent_hours)
    for r in records:
        if r.get("forced"):
            result["forced"] += 1
        else:
            result["blocked"] += 1
        ts = r.get("ts")
        if ts:
            try:
                if datetime.fromisoformat(ts) >= cutoff:
                    result["recent_24h"] += 1
            except ValueError:
                pass

    result["total"] = len(records)
    if records:
        result["latest_ts"] = records[-1].get("ts")
        result["recent"] = records[-limit:]
    return result
