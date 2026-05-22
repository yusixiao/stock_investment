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

        # 分红视图 — 三市场统一 schema:_symbol / date / cash_dividend
        # A 股:从 data/market/A/dividend/*.parquet 直接映射(BaoStock 英文 schema)
        # HK/US:从 cashflow.DIVIDENDS_PAID 派生(粒度仅到年报)
        for market in MARKETS:
            self._setup_dividend_view(market)

        # HK/US daily 视图覆盖:从 indicator 派生 peTTM / pbMRQ
        # A 股 daily 已有 BaoStock 权威估值列,跳过
        for market in ("HK", "US"):
            self._override_daily_with_derived_valuation(market)

        logger.info("DuckDB views created for all market parquet data")

    def _override_daily_with_derived_valuation(self, market: str):
        """用 ASOF LEFT JOIN 把 indicator(EPSJB / BPS)派生的 peTTM/pbMRQ 覆盖到 daily 视图。

        语义说明:
        - HK/US 的 BaoStock-style daily schema 含 peTTM/pbMRQ 列,但 yfinance 抓取流程
          只填 OHLCV,这些列长期为 NULL,导致估值类策略空运。
        - indicator 视图含 EPSJB(每股收益)/ BPS(每股净资产)/ ROEJQ 等,REPORT_DATE
          升序;HK 仅年报粒度(12-31),US 多到年报粒度。因此派生的 peTTM 实质是 PE_LYR,
          pbMRQ 实质是 PB(最新报告期),命名沿用 BaoStock 仅为上层无感。
        - close / NULLIF(EPSJB, 0):EPSJB ≤ 0 时 NULLIF 不生效但分母可能为负,
          因此再用 CASE WHEN EPSJB > 0 才派生,避免负 PE 误导。
        - 币种:HK indicator EPSJB 单位人民币、close 单位港币,直接相除有 ~10% 汇率
          误差,当前阶段忽略(用户决策)。
        """
        daily_view = f"v_{market.lower()}_daily"
        raw_view = f"v_{market.lower()}_daily_raw"
        ind_view = f"v_{market.lower()}_indicator"
        if not self._view_exists(daily_view) or not self._view_exists(ind_view):
            logger.info(
                "Skip derived valuation for %s: %s or %s missing",
                market,
                daily_view,
                ind_view,
            )
            return

        # 先把原 daily 视图 clone 到 _raw,再用 _raw 重建 daily,避免自引用
        daily_dir = MARKET_DIR / market / "daily"
        if not daily_dir.exists():
            return
        glob_pattern = str(daily_dir / "*.parquet")
        try:
            self._conn.execute(f"""
                CREATE OR REPLACE VIEW {raw_view} AS
                SELECT *, regexp_extract(filename, '([^/]+)\\.parquet$', 1) AS _symbol
                FROM read_parquet('{glob_pattern}', filename=true, union_by_name=true)
            """)
        except Exception as e:
            logger.warning(f"Failed to create {raw_view}: {e}")
            return

        # 动态列保留:除估值列外原样保留,估值列用派生值
        try:
            cols = (
                self._conn.execute(f"DESCRIBE {raw_view}")
                .fetchdf()["column_name"]
                .tolist()
            )
        except Exception as e:
            logger.warning(f"DESCRIBE {raw_view} failed: {e}")
            return

        # 动态列保留:除估值列外原样保留,估值列用派生值
        try:
            cols = (
                self._conn.execute(f"DESCRIBE {daily_view}")
                .fetchdf()["column_name"]
                .tolist()
            )
        except Exception as e:
            logger.warning(f"DESCRIBE {daily_view} failed: {e}")
            return

        val_cols = {"peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"}
        keep_cols = [c for c in cols if c not in val_cols]
        # 检查 indicator 视图是否含派生所需字段
        ind_cols = (
            self._conn.execute(f"DESCRIBE {ind_view}").fetchdf()["column_name"].tolist()
        )
        has_eps = "EPSJB" in ind_cols
        has_bps = "BPS" in ind_cols
        if not has_eps and not has_bps:
            logger.info(
                "Skip derived valuation for %s: %s 缺 EPSJB 和 BPS",
                market,
                ind_view,
            )
            return

        keep_select = ", ".join(f"d.{c}" for c in keep_cols)
        pe_expr = (
            "CASE WHEN i.EPSJB > 0 THEN d.close / i.EPSJB ELSE NULL END AS peTTM"
            if has_eps
            else "NULL::DOUBLE AS peTTM"
        )
        pb_expr = (
            "CASE WHEN i.BPS > 0 THEN d.close / i.BPS ELSE NULL END AS pbMRQ"
            if has_bps
            else "NULL::DOUBLE AS pbMRQ"
        )

        sql = f"""
            CREATE OR REPLACE VIEW {daily_view} AS
            SELECT
                {keep_select},
                {pe_expr},
                {pb_expr},
                NULL::DOUBLE AS psTTM,
                NULL::DOUBLE AS pcfNcfTTM
            FROM {raw_view} d
            ASOF LEFT JOIN {ind_view} i
              ON i._symbol = d._symbol
             AND i.REPORT_DATE <= d.date
        """
        try:
            self._conn.execute(sql)
            logger.info(
                "View overridden: %s (peTTM/pbMRQ 从 %s 派生,PE_LYR 语义)",
                daily_view,
                ind_view,
            )
        except Exception as e:
            logger.warning(f"Failed to override {daily_view}: {e}")

    def _setup_dividend_view(self, market: str):
        """创建分红视图。三市场统一 schema:_symbol / date / cash_dividend(每股,>0) / ...

        优先级:
          1. data/market/{market}/dividend/*.parquet 独立文件存在 → 直接映射
             - A 股:EastMoney 抓取(BaoStock 字段名)
             - HK/US:yfinance Ticker.dividends(每股事件级,字段对齐 BaoStock)
          2. 仅 HK/US fallback:从 cashflow.DIVIDENDS_PAID 派生(公司总额,语义弱)

        统一 schema:_symbol / date / cash_dividend / stocks_ps / record_date / pay_date
        独立 parquet 走方案 1 时,cash_dividend 为「每股税前分红」;
        若 HK/US 退化到方案 2,cash_dividend 为「公司总分红现金流出」(语义不一致,
        消费端需谨慎,选股策略应优先依赖方案 1)。
        """
        view_name = f"v_{market.lower()}_dividend"
        div_dir = MARKET_DIR / market / "dividend"
        has_parquet = div_dir.exists() and any(div_dir.glob("*.parquet"))

        if has_parquet:
            glob_pattern = str(div_dir / "*.parquet")
            # BaoStock 字段:dividOperateDate(除权日) / dividCashPsBeforeTax(税前每股) / ...
            sql = f"""
                CREATE OR REPLACE VIEW {view_name} AS
                SELECT
                    regexp_extract(filename, '([^/]+)\\.parquet$', 1) AS _symbol,
                    dividOperateDate AS date,
                    TRY_CAST(dividCashPsBeforeTax AS DOUBLE) AS cash_dividend,
                    TRY_CAST(dividStocksPs AS DOUBLE) AS stocks_ps,
                    dividRegistDate AS record_date,
                    dividPayDate AS pay_date
                FROM read_parquet('{glob_pattern}', filename=true, union_by_name=true)
                WHERE dividOperateDate IS NOT NULL
                  AND TRY_CAST(dividCashPsBeforeTax AS DOUBLE) > 0
            """
            try:
                self._conn.execute(sql)
                logger.debug(f"View created: {view_name} (独立 parquet,每股事件级)")
            except Exception as e:
                logger.warning(f"Failed to create {view_name}: {e}")
            return

        if market == "A":
            logger.info(f"Skip {view_name}: no parquet in {div_dir}")
            return

        # HK/US fallback:cashflow 派生(公司总额,语义弱)
        cashflow_view = f"v_{market.lower()}_cashflow"
        if not self._view_exists(cashflow_view):
            logger.info(f"Skip {view_name}: {cashflow_view} not available")
            return
        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT
                _symbol,
                REPORT_DATE AS date,
                DIVIDENDS_PAID AS cash_dividend,
                NULL::DOUBLE AS stocks_ps,
                NULL::VARCHAR AS record_date,
                NULL::VARCHAR AS pay_date
            FROM {cashflow_view}
            WHERE DIVIDENDS_PAID IS NOT NULL AND DIVIDENDS_PAID > 0
        """
        try:
            self._conn.execute(sql)
            logger.warning(
                f"View created: {view_name} (从 {cashflow_view} 派生 — "
                f"cash_dividend 为公司总额非每股,选股策略慎用)"
            )
        except Exception as e:
            logger.warning(f"Failed to create {view_name}: {e}")

    def _view_exists(self, view_name: str) -> bool:
        try:
            n = self._conn.execute(
                "SELECT count(*) FROM duckdb_views() WHERE view_name = ?",
                [view_name],
            ).fetchone()[0]
            return n > 0
        except Exception:
            return False

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

    # -------- 业务层 bulk 查询入口(替代旧 parquet glob) --------

    def _bulk_split(self, df: pd.DataFrame, sort_col: str) -> dict[str, pd.DataFrame]:
        """共用:按 _symbol 切分 + 按 sort_col 升序 + reset_index。空 df → {}"""
        if df.empty:
            return {}
        result: dict[str, pd.DataFrame] = {}
        for sym, g in df.groupby("_symbol", sort=False):
            sub = g.drop(columns="_symbol").sort_values(sort_col).reset_index(drop=True)
            result[sym] = sub
        return result

    def query_valuation_bulk(
        self,
        market: str,
        symbols: Optional[list[str]] = None,
    ) -> dict[str, pd.DataFrame]:
        """批量取估值序列(date/peTTM/pbMRQ/psTTM/pcfNcfTTM)。
        A 股直接来自 v_a_daily 的估值列;HK/US daily 不含估值时返回空 dict。
        """
        view = f"v_{market.lower()}_daily"
        # 检查列是否存在(HK/US daily 可能没有估值列)
        cols = self._conn.execute(f"DESCRIBE {view}").fetchdf()["column_name"].tolist()
        val_cols = [c for c in ("peTTM", "pbMRQ", "psTTM", "pcfNcfTTM") if c in cols]
        if not val_cols:
            return {}
        select = ", ".join(["_symbol", "date"] + val_cols)
        params: list = []
        where = ""
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            where = f"WHERE _symbol IN ({placeholders})"
            params.extend(symbols)
        sql = f"SELECT {select} FROM {view} {where} ORDER BY _symbol, date"
        df = self._conn.execute(sql, params).fetchdf()
        return self._bulk_split(df, sort_col="date")

    def query_dividend_bulk(
        self,
        market: str,
        symbols: Optional[list[str]] = None,
    ) -> dict[str, pd.DataFrame]:
        """批量取分红事件序列。视图 v_{x}_dividend 不存在时返回空 dict。"""
        view = f"v_{market.lower()}_dividend"
        if not self._view_exists(view):
            return {}
        params: list = []
        where = ""
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            where = f"WHERE _symbol IN ({placeholders})"
            params.extend(symbols)
        sql = f"SELECT * FROM {view} {where} ORDER BY _symbol, date"
        df = self._conn.execute(sql, params).fetchdf()
        return self._bulk_split(df, sort_col="date")

    def query_financial_bulk(
        self,
        market: str,
        symbols: Optional[list[str]] = None,
        fin_type: str = "indicator",
    ) -> dict[str, pd.DataFrame]:
        """批量取财务序列(默认 indicator,REPORT_DATE 升序)。
        视图缺失返回 {}。
        """
        view = f"v_{market.lower()}_{fin_type}"
        if not self._view_exists(view):
            return {}
        params: list = []
        where = ""
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            where = f"WHERE _symbol IN ({placeholders})"
            params.extend(symbols)
        sql = f"SELECT * FROM {view} {where} ORDER BY _symbol, REPORT_DATE"
        df = self._conn.execute(sql, params).fetchdf()
        return self._bulk_split(df, sort_col="REPORT_DATE")

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


def reload_views():
    """重新创建所有视图(用于运行期补落新数据后刷新视图,无需重启进程)。"""
    store = get_store()
    store._setup_views()
    logger.info("DuckDB views reloaded")


def shutdown_duckdb():
    global _store
    if _store is not None:
        _store.close()
        _store = None
