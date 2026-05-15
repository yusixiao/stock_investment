from pathlib import Path
from typing import List, Optional

from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.repositories.base import (
    read_parquet_as_models,
    write_models_as_parquet,
    append_models_to_parquet,
)


class MarketRepository:
    """行情数据持久化 — 日K线 + 复权因子"""

    def __init__(self, daily_dir: Path, adjust_factor_dir: Path):
        self._daily_dir = daily_dir
        self._adjust_dir = adjust_factor_dir

    def _daily_path(self, code: str) -> Path:
        return self._daily_dir / f"{code}.parquet"

    def _adjust_path(self, code: str) -> Path:
        return self._adjust_dir / f"{code}.parquet"

    def read_daily_kline(self, code: str) -> List[DailyKlineRecord]:
        return read_parquet_as_models(
            self._daily_path(code), DailyKlineRecord, sort_by="date", ascending=False
        )

    def write_daily_kline(self, code: str, records: List[DailyKlineRecord]) -> None:
        write_models_as_parquet(
            self._daily_path(code), records, sort_by="date", ascending=False
        )

    def append_daily_kline(
        self, code: str, new_records: List[DailyKlineRecord]
    ) -> None:
        append_models_to_parquet(
            self._daily_path(code),
            new_records,
            DailyKlineRecord,
            dedup_key="date",
            sort_by="date",
            ascending=False,
        )

    def read_adjust_factor(self, code: str) -> List[AdjustFactorRecord]:
        return read_parquet_as_models(
            self._adjust_path(code),
            AdjustFactorRecord,
            sort_by="dividOperateDate",
            ascending=True,
        )

    def write_adjust_factor(self, code: str, records: List[AdjustFactorRecord]) -> None:
        write_models_as_parquet(
            self._adjust_path(code), records, sort_by="dividOperateDate", ascending=True
        )

    def list_codes(self) -> List[str]:
        """列出所有已有日K线数据的股票代码"""
        if not self._daily_dir.exists():
            return []
        return [p.stem for p in self._daily_dir.glob("*.parquet")]

    def get_latest_date(self, code: str) -> Optional[str]:
        """获取某只股票的最新日期（只读 date 列，取最大值）"""
        import pandas as pd

        path = self._daily_path(code)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path, columns=["date"])
            if df.empty:
                return None
            return str(df["date"].max())
        except Exception:
            return None
