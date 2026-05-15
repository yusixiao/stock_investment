from pathlib import Path
from typing import List

import pandas as pd

from backend.models.basic import StockBasicInfo
from backend.repositories.base import read_parquet_as_models, write_models_as_parquet


class BasicRepository:
    """基础数据持久化 — 股票列表（单文件）"""

    def __init__(self, basic_dir: Path):
        self._path = basic_dir / "stock_list.parquet"

    def read_stock_list(self) -> List[StockBasicInfo]:
        return read_parquet_as_models(
            self._path, StockBasicInfo, sort_by="code", ascending=True
        )

    def write_stock_list(self, records: List[StockBasicInfo]) -> None:
        write_models_as_parquet(self._path, records, sort_by="code", ascending=True)

    def get_by_code(self, code: str) -> StockBasicInfo | None:
        """按代码查找单只股票信息"""
        if not self._path.exists():
            return None
        df = pd.read_parquet(self._path)
        matched = df[df["code"] == code]
        if matched.empty:
            return None
        row = matched.iloc[0].where(matched.iloc[0].notna(), None).to_dict()
        return StockBasicInfo.model_validate(row)
