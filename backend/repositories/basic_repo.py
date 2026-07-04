from pathlib import Path
from typing import List

import pandas as pd

from backend.models.basic import StockBasicInfo
from backend.repositories.base import (
    IntegrityPolicy,
    read_parquet_as_models,
    write_models_as_parquet,
)

# 股票列表是全量快照(重算型): IPO 增行 / 退市减行 / 名称行业变更均合法, 不做逐行
# 值校验; 只护结构(整列消失)与灾难性骤减(数据源半拉子返回, <50% 视为异常)。
_STOCK_LIST_INTEGRITY = IntegrityPolicy(key="code", mode="recompute")


class BasicRepository:
    """基础数据持久化 — 股票列表（单文件）"""

    def __init__(self, basic_dir: Path):
        self._path = basic_dir / "stock_list.parquet"

    def read_stock_list(self) -> List[StockBasicInfo]:
        return read_parquet_as_models(
            self._path, StockBasicInfo, sort_by="code", ascending=True
        )

    def write_stock_list(self, records: List[StockBasicInfo]) -> None:
        write_models_as_parquet(
            self._path,
            records,
            sort_by="code",
            ascending=True,
            integrity=_STOCK_LIST_INTEGRITY,
        )

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
