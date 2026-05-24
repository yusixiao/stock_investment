from pathlib import Path
from typing import List, Type, TypeVar

import pandas as pd
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


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
) -> None:
    """将 Pydantic 模型列表写入 parquet 文件"""
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    dicts = [r.model_dump(exclude_none=False) for r in records]
    df = pd.DataFrame(dicts)
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
    df.to_parquet(path, index=False)


def append_models_to_parquet(
    path: Path,
    new_records: List[T],
    model_class: Type[T],
    dedup_key="date",
    sort_by: str = "date",
    ascending: bool = False,
) -> None:
    """增量追加记录到 parquet 文件，按 dedup_key 去重。

    dedup_key 支持单字段 str(向后兼容)或复合键 tuple/list:
        dedup_key="REPORT_DATE"               # 单键
        dedup_key=("END_DATE", "HOLDER_RANK")  # 复合键(§7 多行/期场景)

    冲突策略: 新记录覆盖旧记录 — 重要,因为下游可能在盘中误抓 partial bar,
    收盘后需要被完整收盘数据覆盖。"""
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
    write_models_as_parquet(path, deduped, sort_by=sort_by, ascending=ascending)
