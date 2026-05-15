"""
DuckDB 查询层 — 直接用 read_parquet() 查询现有 parquet 文件，不导入数据。
提供视图注册 + 便捷查询方法。
"""

import logging
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from config import MARKET_DIR

logger = logging.getLogger(__name__)

MARKETS = ["A", "HK", "US"]
FINANCIAL_TYPES = ["income", "balance", "cashflow", "indicator"]


class DuckDBStore:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = duckdb.connect(db_path)
        self._setup_views()

    def _setup_views(self):
        """为所有市场的 parquet 数据创建视图"""
        for market in MARKETS:
            market_dir = MARKET_DIR / market

            # 日K线视图: v_{market}_daily
            daily_dir = market_dir / "daily"
            if daily_dir.exists():
                self._create_glob_view(f"v_{market.lower()}_daily", daily_dir)

            # 复权因子视图: v_{market}_adjust_factor
            adj_dir = market_dir / "adjust_factor"
            if adj_dir.exists():
                self._create_glob_view(f"v_{market.lower()}_adjust_factor", adj_dir)

            # 财务数据视图: v_{market}_{type}
            for fin_type in FINANCIAL_TYPES:
                fin_dir = market_dir / "financial" / fin_type
                if fin_dir.exists():
                    self._create_glob_view(f"v_{market.lower()}_{fin_type}", fin_dir)

        logger.info("DuckDB views created for all market parquet data")

    def _create_glob_view(self, view_name: str, directory: Path):
        """用 read_parquet glob 创建视图，filename 提取股票代码"""
        glob_pattern = str(directory / "*.parquet")
        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT *, regexp_extract(filename, '([^/]+)\\.parquet$', 1) AS _symbol
            FROM read_parquet('{glob_pattern}', filename=true, union_by_name=true)
        """
        try:
            self._conn.execute(sql)
            logger.debug(f"View created: {view_name}")
        except Exception as e:
            logger.warning(f"Failed to create view {view_name}: {e}")

    def query(self, sql: str, params: Optional[list] = None) -> pd.DataFrame:
        """执行 SQL 查询，返回 DataFrame"""
        if params:
            return self._conn.execute(sql, params).fetchdf()
        return self._conn.execute(sql).fetchdf()

    def query_kline(
        self,
        market: str,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """查询单只股票 K线数据"""
        view = f"v_{market.lower()}_daily"
        conditions = ["_symbol = ?"]
        params = [symbol]

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM {view} WHERE {where} ORDER BY date"
        if limit:
            sql += f" LIMIT {limit}"

        return self._conn.execute(sql, params).fetchdf()

    def query_financial(
        self,
        market: str,
        fin_type: str,
        symbol: str,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """查询单只股票财务数据"""
        view = f"v_{market.lower()}_{fin_type}"
        sql = f"SELECT * FROM {view} WHERE _symbol = ? ORDER BY REPORT_DATE DESC"
        if limit:
            sql += f" LIMIT {limit}"
        return self._conn.execute(sql, [symbol]).fetchdf()

    def search_symbols(self, market: str, pattern: str) -> list[str]:
        """模糊搜索股票代码"""
        view = f"v_{market.lower()}_daily"
        sql = f"SELECT DISTINCT _symbol FROM {view} WHERE _symbol ILIKE ? LIMIT 50"
        df = self._conn.execute(sql, [f"%{pattern}%"]).fetchdf()
        return df["_symbol"].tolist()

    def list_symbols(self, market: str) -> list[str]:
        """列出某市场所有股票代码"""
        view = f"v_{market.lower()}_daily"
        sql = f"SELECT DISTINCT _symbol FROM {view} ORDER BY _symbol"
        df = self._conn.execute(sql).fetchdf()
        return df["_symbol"].tolist()

    def screen(self, sql: str, params: Optional[list] = None) -> pd.DataFrame:
        """执行自定义筛选 SQL（跨股票）"""
        return self.query(sql, params)

    def close(self):
        self._conn.close()


_store: Optional[DuckDBStore] = None


def get_store() -> DuckDBStore:
    global _store
    if _store is None:
        _store = DuckDBStore()
    return _store


def init_duckdb():
    """应用启动时调用，初始化 DuckDB 查询层"""
    get_store()
    logger.info("DuckDB store initialized")


def shutdown_duckdb():
    global _store
    if _store is not None:
        _store.close()
        _store = None
