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

    def query_qfq_kline(
        self,
        market: str,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        查询前复权 K 线（DuckDB ASOF JOIN 派生）。

        实现：用 ASOF LEFT JOIN 把每根日线绑定到 dividOperateDate <= date 的最新
        foreAdjustFactor，前复权价 = raw * COALESCE(factor, 1.0)。
        - BaoStock 语义下 foreAdjustFactor 已归一化到最新日期=1.0，因此 close * factor
          直接得到前复权价，无需额外归一化除法。
        - 早于首次除权 / 无除权数据时 ASOF 命中 NULL，COALESCE 退化为 1.0 即等价 raw。

        返回 7 列：date / open / high / low / close / volume / amount，date 升序。
        """
        daily_view = f"v_{market.lower()}_daily"
        adj_view = f"v_{market.lower()}_adjust_factor"

        # 仅当复权视图存在时才 ASOF JOIN，否则直接读 daily（防御视图未注册）
        adj_exists = (
            self._conn.execute(
                "SELECT count(*) FROM duckdb_views() WHERE view_name = ?",
                [adj_view],
            ).fetchone()[0]
            > 0
        )

        conditions = ["d._symbol = ?"]
        params: list = [symbol]
        if start:
            conditions.append("d.date >= ?")
            params.append(start)
        if end:
            conditions.append("d.date <= ?")
            params.append(end)
        where = " AND ".join(conditions)

        if adj_exists:
            sql = f"""
                SELECT d.date,
                       d.open   * COALESCE(af.foreAdjustFactor, 1.0) AS open,
                       d.high   * COALESCE(af.foreAdjustFactor, 1.0) AS high,
                       d.low    * COALESCE(af.foreAdjustFactor, 1.0) AS low,
                       d.close  * COALESCE(af.foreAdjustFactor, 1.0) AS close,
                       d.volume,
                       d.amount
                FROM {daily_view} d
                ASOF LEFT JOIN {adj_view} af
                  ON af._symbol = d._symbol
                 AND af.dividOperateDate <= d.date
                WHERE {where}
                ORDER BY d.date ASC
            """
        else:
            sql = f"""
                SELECT d.date, d.open, d.high, d.low, d.close, d.volume, d.amount
                FROM {daily_view} d
                WHERE {where}
                ORDER BY d.date ASC
            """
        return self._conn.execute(sql, params).fetchdf()

    def query_qfq_kline_bulk(
        self,
        market: str,
        symbols: Optional[list[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict[str, pd.DataFrame]:
        """
        批量查询多只股票的前复权 K 线，一次 SQL + groupby 拆 dict。

        相对 query_qfq_kline 循环调用,在全市场场景下可加速 ~240x
        (实测 A 股 5524 只 × 20 年:循环 ~32 分钟 → bulk ~8 秒)。

        参数
        - symbols: 为空/None 时返回该市场所有 symbol 的数据
        - start/end: 闭区间日期过滤,None 则不限

        返回
        - {symbol: DataFrame(date, open, high, low, close, volume, amount)},
          DataFrame 按日期升序,index 重置;空数据的 symbol 不会出现在 dict 中。
        """
        daily_view = f"v_{market.lower()}_daily"
        adj_view = f"v_{market.lower()}_adjust_factor"

        adj_exists = (
            self._conn.execute(
                "SELECT count(*) FROM duckdb_views() WHERE view_name = ?",
                [adj_view],
            ).fetchone()[0]
            > 0
        )

        conditions: list[str] = []
        params: list = []
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            conditions.append(f"d._symbol IN ({placeholders})")
            params.extend(symbols)
        if start:
            conditions.append("d.date >= ?")
            params.append(start)
        if end:
            conditions.append("d.date <= ?")
            params.append(end)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        if adj_exists:
            sql = f"""
                SELECT d._symbol,
                       d.date,
                       d.open   * COALESCE(af.foreAdjustFactor, 1.0) AS open,
                       d.high   * COALESCE(af.foreAdjustFactor, 1.0) AS high,
                       d.low    * COALESCE(af.foreAdjustFactor, 1.0) AS low,
                       d.close  * COALESCE(af.foreAdjustFactor, 1.0) AS close,
                       d.volume,
                       d.amount
                FROM {daily_view} d
                ASOF LEFT JOIN {adj_view} af
                  ON af._symbol = d._symbol
                 AND af.dividOperateDate <= d.date
                {where}
                ORDER BY d._symbol, d.date ASC
            """
        else:
            sql = f"""
                SELECT d._symbol, d.date, d.open, d.high, d.low, d.close,
                       d.volume, d.amount
                FROM {daily_view} d
                {where}
                ORDER BY d._symbol, d.date ASC
            """

        df = self._conn.execute(sql, params).fetchdf()
        if df.empty:
            return {}
        # groupby 拆 dict;drop _symbol 列,index 重置以保持与 query_qfq_kline 一致
        result: dict[str, pd.DataFrame] = {}
        for sym, g in df.groupby("_symbol", sort=False):
            sub = g.drop(columns="_symbol").reset_index(drop=True)
            result[sym] = sub
        return result

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


def init_duckdb_with_health_check():
    """启动时初始化 DuckDB 并对 A 股核心视图做健康检查。

    检查 v_a_daily / v_a_adjust_factor 是否非空，任一失败抛 RuntimeError，
    阻止应用在缺数据情况下启动（D8 风险缓解）。
    """
    init_duckdb()
    store = get_store()

    # 检查 A 股日线视图：缺 parquet 会导致视图未注册或行数为 0
    try:
        a_symbols = store.list_symbols("A")
    except Exception as e:
        raise RuntimeError(
            "DuckDB health check failed: v_a_daily not available "
            f"(data/market/A/daily/ has no parquet): {e}"
        )
    if len(a_symbols) == 0:
        raise RuntimeError(
            "DuckDB health check failed: v_a_daily empty, "
            "data/market/A/daily/ has no parquet"
        )

    # 检查 A 股复权因子视图
    try:
        af_count = store._conn.execute(
            "SELECT count(*) AS c FROM v_a_adjust_factor"
        ).fetchone()[0]
    except Exception as e:
        raise RuntimeError(
            "DuckDB health check failed: v_a_adjust_factor not available "
            f"(data/market/A/adjust_factor/ has no parquet): {e}"
        )
    if af_count == 0:
        raise RuntimeError(
            "DuckDB health check failed: v_a_adjust_factor empty, "
            "data/market/A/adjust_factor/ has no parquet"
        )

    logger.info(
        "DuckDB health check passed: %d A symbols, %d adjust_factor rows",
        len(a_symbols),
        af_count,
    )


def shutdown_duckdb():
    global _store
    if _store is not None:
        _store.close()
        _store = None
