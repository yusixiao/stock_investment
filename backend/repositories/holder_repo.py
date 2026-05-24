"""§7 控股股东 — Repository(parquet I/O)。

3 张表分目录存:
- top10/<code>.parquet         — 十大股东(全部口径)
- top10_free/<code>.parquet    — 十大流通股东
- holder_count/<code>.parquet  — 股东户数(单期 + PRE_END_DATE 上期)

dedup 策略:
- top10 / top10_free:复合键 (END_DATE, HOLDER_RANK)
- holder_count:单键 END_DATE
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from backend.models.holder import (
    Top10HolderRecord,
    Top10FreeHolderRecord,
    HolderCountRecord,
)
from backend.repositories.base import (
    read_parquet_as_models,
    write_models_as_parquet,
    append_models_to_parquet,
)


class HolderRepository:
    def __init__(self, holders_dir: Path):
        self._top10_dir = Path(holders_dir) / "top10"
        self._top10_free_dir = Path(holders_dir) / "top10_free"
        self._holder_count_dir = Path(holders_dir) / "holder_count"

    @staticmethod
    def _path(base: Path, code: str) -> Path:
        return base / f"{code}.parquet"

    # ---------- 十大股东 ----------
    def read_top10_holders(self, code: str) -> List[Top10HolderRecord]:
        return read_parquet_as_models(
            self._path(self._top10_dir, code),
            Top10HolderRecord,
            sort_by="END_DATE",
            ascending=False,
        )

    def write_top10_holders(self, code: str, records: List[Top10HolderRecord]) -> None:
        write_models_as_parquet(
            self._path(self._top10_dir, code),
            records,
            sort_by="END_DATE",
            ascending=False,
        )

    def append_top10_holders(
        self, code: str, new_records: List[Top10HolderRecord]
    ) -> None:
        append_models_to_parquet(
            self._path(self._top10_dir, code),
            new_records,
            Top10HolderRecord,
            dedup_key=("END_DATE", "HOLDER_RANK"),
            sort_by="END_DATE",
            ascending=False,
        )

    # ---------- 十大流通股东 ----------
    def read_top10_free_holders(self, code: str) -> List[Top10FreeHolderRecord]:
        return read_parquet_as_models(
            self._path(self._top10_free_dir, code),
            Top10FreeHolderRecord,
            sort_by="END_DATE",
            ascending=False,
        )

    def write_top10_free_holders(
        self, code: str, records: List[Top10FreeHolderRecord]
    ) -> None:
        write_models_as_parquet(
            self._path(self._top10_free_dir, code),
            records,
            sort_by="END_DATE",
            ascending=False,
        )

    def append_top10_free_holders(
        self, code: str, new_records: List[Top10FreeHolderRecord]
    ) -> None:
        append_models_to_parquet(
            self._path(self._top10_free_dir, code),
            new_records,
            Top10FreeHolderRecord,
            dedup_key=("END_DATE", "HOLDER_RANK"),
            sort_by="END_DATE",
            ascending=False,
        )

    # ---------- 股东户数 ----------
    def read_holder_count(self, code: str) -> List[HolderCountRecord]:
        return read_parquet_as_models(
            self._path(self._holder_count_dir, code),
            HolderCountRecord,
            sort_by="END_DATE",
            ascending=False,
        )

    def write_holder_count(self, code: str, records: List[HolderCountRecord]) -> None:
        write_models_as_parquet(
            self._path(self._holder_count_dir, code),
            records,
            sort_by="END_DATE",
            ascending=False,
        )

    def append_holder_count(
        self, code: str, new_records: List[HolderCountRecord]
    ) -> None:
        append_models_to_parquet(
            self._path(self._holder_count_dir, code),
            new_records,
            HolderCountRecord,
            dedup_key="END_DATE",
            sort_by="END_DATE",
            ascending=False,
        )

    # ---------- 缓存元信息 ----------
    def parquet_path(self, code: str, table: str) -> Path:
        """返回某 (code, table) 对应 parquet 路径(供 updater mtime 判断)。"""
        mapping = {
            "top10": self._top10_dir,
            "top10_free": self._top10_free_dir,
            "holder_count": self._holder_count_dir,
        }
        if table not in mapping:
            raise ValueError(f"unknown holder table: {table}")
        return self._path(mapping[table], code)
