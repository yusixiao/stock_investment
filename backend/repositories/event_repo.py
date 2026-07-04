from pathlib import Path
from typing import List

from backend.models.event import DividendRecord
from backend.repositories.base import (
    IntegrityPolicy,
    read_parquet_as_models,
    write_models_as_parquet,
)

# 分红台账型: 历史除权事件不可被 null/删除。已公告分红的金额修正(方案→实施)属
# 合法值变更(ledger 放行), 非空→null / 整列消失 / 行数骤减则拦截。
_DIVIDEND_INTEGRITY = IntegrityPolicy(key="dividOperateDate", mode="ledger")


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
            integrity=_DIVIDEND_INTEGRITY,
        )

    def list_codes(self) -> List[str]:
        if not self._dividend_dir.exists():
            return []
        return [p.stem for p in self._dividend_dir.glob("*.parquet")]
