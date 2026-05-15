from pathlib import Path
from typing import List

from backend.models.event import DividendRecord
from backend.repositories.base import (
    read_parquet_as_models,
    write_models_as_parquet,
)


class EventRepository:
    """事件数据持久化 — 分红/送转"""

    def __init__(self, event_dir: Path):
        self._dividend_dir = event_dir / "dividend"

    def _dividend_path(self, code: str) -> Path:
        return self._dividend_dir / f"{code}.parquet"

    def read_dividends(self, code: str) -> List[DividendRecord]:
        return read_parquet_as_models(
            self._dividend_path(code),
            DividendRecord,
            sort_by="dividOperateDate",
            ascending=False,
        )

    def write_dividends(self, code: str, records: List[DividendRecord]) -> None:
        write_models_as_parquet(
            self._dividend_path(code),
            records,
            sort_by="dividOperateDate",
            ascending=False,
        )

    def list_codes(self) -> List[str]:
        if not self._dividend_dir.exists():
            return []
        return [p.stem for p in self._dividend_dir.glob("*.parquet")]
