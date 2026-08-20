"""
DuckDB 查询层 — 直接用 read_parquet() 查询现有 parquet 文件，不导入数据。
提供视图注册 + 便捷查询方法。
"""

import logging
import threading
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
        # DuckDB 单连接非线程安全:多线程并发 execute 会让 cursor 状态相互踩坏,
        # fetchone()/fetchdf() 可能返回 None。data_cache 启动时三市并发 reload
        # 必须串行。所有公共并发热点方法(bulk / for_section)入口加锁。RLock
        # 允许同一线程重入(query_qfq_kline_bulk 内部又 query duckdb_views)。
        self._lock = threading.RLock()
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

            # 指数视图: v_{market}_index
            # ⚠️ 指数独立于个股 daily:不做复权 ASOF JOIN、不做估值覆盖,
            # 也不会进 query_qfq_kline_bulk 的股票 universe。
            index_dir = market_dir / "index"
            if index_dir.exists():
                self._create_glob_view(f"v_{market.lower()}_index", index_dir)

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

        # 港股通成分股快照视图(只在 HK 上有意义,需在 periodic_report 之前建好)
        # 数据落点 data/market/HK/membership/hk_connect.parquet,只读最新 as_of_date
        self._setup_hk_connect_view()

        # 港股 sector/industry 视图(yfinance 周更,落 hk_industry.parquet)
        self._setup_hk_industry_view()

        # 业务视图层:v_{market}_periodic_report
        # 把 indicator + income + balance + cashflow 按 (_symbol, REPORT_DATE) LEFT JOIN
        # 同义字段 COALESCE 统一(MONETARYFUNDS / CAPEX),
        # A 股独有字段在 HK/US 视图中显式 SELECT NULL 占位,保持三市场列对齐。
        for market in MARKETS:
            self._setup_periodic_report_view(market)

        logger.info("DuckDB views created for all market parquet data")

    def _setup_hk_connect_view(self):
        """创建港股通成分股最新快照视图 v_hk_connect_latest。

        数据来源:data/market/HK/membership/hk_connect.parquet(单文件 append 多日快照)
        视图取 as_of_date 最大值的全部行,等价"当前港股通成分股名单"。

        schema: code (5 位 HK 代码) / name / board / as_of_date

        ⚠️ 仅当前快照,无历史进出名单。回测严格 PIT 判断不适用。
        """
        path = MARKET_DIR / "HK" / "membership" / "hk_connect.parquet"
        if not path.exists():
            logger.info("Skip v_hk_connect_latest: parquet 不存在 (%s)", path)
            return
        try:
            # ⚠️ DuckDB 在某些 parquet 写法下 MAX(VARCHAR) 会截断字符串(实测
            # '2026-06-01' → '2026-06-'),改 CAST AS DATE 比较绕过该 bug
            self._conn.execute(f"""
                CREATE OR REPLACE VIEW v_hk_connect_latest AS
                SELECT code, name, board, as_of_date
                FROM read_parquet('{path}')
                WHERE CAST(as_of_date AS DATE) =
                      (SELECT MAX(CAST(as_of_date AS DATE)) FROM read_parquet('{path}'))
            """)
            logger.info("View created: v_hk_connect_latest (港股通最新快照)")
        except Exception as e:
            logger.warning(f"Failed to create v_hk_connect_latest: {e}")

    def _setup_hk_industry_view(self):
        """创建港股 sector/industry 视图 v_hk_industry。

        数据来源:data/market/HK/membership/hk_industry.parquet
        schema: code / name / sector / industry / updated_at
        """
        path = MARKET_DIR / "HK" / "membership" / "hk_industry.parquet"
        if not path.exists():
            logger.info("Skip v_hk_industry: parquet 不存在 (%s)", path)
            return
        try:
            self._conn.execute(f"""
                CREATE OR REPLACE VIEW v_hk_industry AS
                SELECT code, name, sector, industry, updated_at
                FROM read_parquet('{path}')
            """)
            logger.info("View created: v_hk_industry (港股行业分类)")
        except Exception as e:
            logger.warning(f"Failed to create v_hk_industry: {e}")

    def refresh_hk_industry_view(self) -> None:
        """对外暴露:hk_industry parquet 写入后重建视图。"""
        self._setup_hk_industry_view()
        logger.info("v_hk_industry refreshed")

    def refresh_index_view(self, market: str) -> None:
        """对外暴露:index parquet 写入后重建 v_{market}_index 视图。"""
        index_dir = MARKET_DIR / market / "index"
        if index_dir.exists():
            self._create_glob_view(f"v_{market.lower()}_index", index_dir)
            logger.info("v_%s_index refreshed", market.lower())

    def refresh_hk_connect_view(self) -> None:
        """对外暴露:hk_connect parquet 写入后重建 v_hk_connect_latest +
        重建 v_hk_periodic_report(后者的 is_hk_connect 表达式在 init 时被
        baked,parquet 从无到有时必须重建才能让 JOIN 生效)。"""
        self._setup_hk_connect_view()
        self._setup_periodic_report_view("HK")
        logger.info("hk_connect views refreshed (latest + v_hk_periodic_report)")

    def _setup_periodic_report_view(self, market: str):
        """构建 v_{market}_periodic_report 业务视图。

        语义:把 4 张周期性 raw 视图(indicator/income/balance/cashflow)按
        (_symbol, REPORT_DATE) LEFT JOIN 成单一视图,屏蔽三市场 schema 差异。

        字段策略:
          - 三市场共有的「业务列」直接保留原名(EPSJB/ROEJQ/PARENT_NETPROFIT 等)
          - 同义字段 COALESCE 统一输出名:
              * MONETARYFUNDS = balance.MONETARYFUNDS (A) 或 balance.CASH_EQUIVALENTS (HK/US)
              * CAPEX = cashflow.CONSTRUCT_LONG_ASSET (A) 或 cashflow.CAPEX (HK/US)
          - A 股独有字段(HK/US 物理表无)在 HK/US 视图中 SELECT NULL 占位
            (TOTAL_SHARE / FCFF_BACK / PARENTNETPROFIT / PARENTNETPROFITTZ /
             INDUSTRY_NAME / TOTAL_OPERATE_INCOME / DEDUCT_PARENT_NETPROFIT)

        消费端:strategies/utils 通过 ctx.get_financial / get_balance / get_cashflow
        访问该视图;A 股独有字段在 HK/US 上得到 NULL,业务代码须容错(已实现)。
        """
        view = f"v_{market.lower()}_periodic_report"
        ind = f"v_{market.lower()}_indicator"
        inc = f"v_{market.lower()}_income"
        bal = f"v_{market.lower()}_balance"
        cf = f"v_{market.lower()}_cashflow"
        for v in (ind, inc, bal, cf):
            if not self._view_exists(v):
                logger.info(f"Skip {view}: prerequisite {v} missing")
                return

        # ── A 独有字段在三市场的物理映射 ──
        # 用 IS / IS NOT 判断列存在性,生成对应 SELECT 表达式
        ind_cols = set(
            self._conn.execute(f"DESCRIBE {ind}").fetchdf()["column_name"].tolist()
        )
        inc_cols = set(
            self._conn.execute(f"DESCRIBE {inc}").fetchdf()["column_name"].tolist()
        )
        bal_cols = set(
            self._conn.execute(f"DESCRIBE {bal}").fetchdf()["column_name"].tolist()
        )
        cf_cols = set(
            self._conn.execute(f"DESCRIBE {cf}").fetchdf()["column_name"].tolist()
        )

        def col_or_null(
            table_alias: str, col: str, present: set, dtype: str = "DOUBLE"
        ) -> str:
            """列存在则 SELECT 该列,否则 NULL 占位。"""
            if col in present:
                return f"{table_alias}.{col}"
            return f"NULL::{dtype} AS {col}"

        # MONETARYFUNDS 同义统一
        if "MONETARYFUNDS" in bal_cols:
            monetary = "b.MONETARYFUNDS"
        elif "CASH_EQUIVALENTS" in bal_cols:
            monetary = "b.CASH_EQUIVALENTS AS MONETARYFUNDS"
        else:
            monetary = "NULL::DOUBLE AS MONETARYFUNDS"

        # CAPEX 同义统一(A 用 CONSTRUCT_LONG_ASSET,HK/US 用 CAPEX)
        # 同时保留 CONSTRUCT_LONG_ASSET 别名(strategies/utils 现仍引用)
        if "CONSTRUCT_LONG_ASSET" in cf_cols:
            capex_expr = (
                "c.CONSTRUCT_LONG_ASSET AS CAPEX, "
                "c.CONSTRUCT_LONG_ASSET AS CONSTRUCT_LONG_ASSET"
            )
        elif "CAPEX" in cf_cols:
            capex_expr = "c.CAPEX AS CAPEX, c.CAPEX AS CONSTRUCT_LONG_ASSET"
        else:
            capex_expr = "NULL::DOUBLE AS CAPEX, NULL::DOUBLE AS CONSTRUCT_LONG_ASSET"

        # is_hk_connect 列:HK 视图 LEFT JOIN v_hk_connect_latest;A/US 永远 FALSE
        # ⚠️ 当前实现是 latest snapshot,所有历史 REPORT_DATE 行都用同一份 membership
        # (look-ahead bias),适合 UI / 粗筛,不适合严格 PIT 回测
        if market == "HK" and self._view_exists("v_hk_connect_latest"):
            hk_connect_join = (
                "LEFT JOIN v_hk_connect_latest hc "
                "ON hc.code = SPLIT_PART(i._symbol, '.', 1)"
            )
            is_hk_connect_expr = "(hc.code IS NOT NULL) AS is_hk_connect"
        else:
            hk_connect_join = ""
            is_hk_connect_expr = "FALSE AS is_hk_connect"

        sql = f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT
                i._symbol,
                i.REPORT_DATE,

                -- ── indicator: 三市场共有 14 列 ──
                {col_or_null("i", "EPSJB", ind_cols)},
                {col_or_null("i", "ROEJQ", ind_cols)},
                {col_or_null("i", "ROA", ind_cols)},
                {col_or_null("i", "ROIC", ind_cols)},
                {col_or_null("i", "BPS", ind_cols)},
                {col_or_null("i", "DILUTED_EPS", ind_cols)},
                {col_or_null("i", "XSMLL", ind_cols)},
                {col_or_null("i", "XSJLL", ind_cols)},
                {col_or_null("i", "ZCFZL", ind_cols)},
                {col_or_null("i", "LD", ind_cols)},
                {col_or_null("i", "GROSS_PROFIT_YOY", ind_cols)},
                {col_or_null("i", "OPERATE_INCOME_YOY", ind_cols)},
                {col_or_null("i", "PARENT_NETPROFIT_YOY", ind_cols)},

                -- ── indicator: A 股独有(HK/US NULL) ──
                {col_or_null("i", "PARENTNETPROFIT", ind_cols)},
                {col_or_null("i", "TOTAL_SHARE", ind_cols)},
                {col_or_null("i", "FCFF_BACK", ind_cols)},
                {col_or_null("i", "PARENTNETPROFITTZ", ind_cols)},

                -- ── income: 三市场共有 ──
                {col_or_null("inc", "PARENT_NETPROFIT", inc_cols)},
                {col_or_null("inc", "NETPROFIT", inc_cols)},
                {col_or_null("inc", "OPERATE_INCOME", inc_cols)},
                {col_or_null("inc", "OPERATE_PROFIT", inc_cols)},
                {col_or_null("inc", "TOTAL_PROFIT", inc_cols)},
                {col_or_null("inc", "BASIC_EPS", inc_cols)},
                {col_or_null("inc", "OPERATE_EXPENSE", inc_cols)},
                {col_or_null("inc", "FINANCE_EXPENSE", inc_cols)},
                {col_or_null("inc", "INCOME_TAX", inc_cols)},

                -- ── income: A 股独有 / 部分市场缺失 ──
                {col_or_null("inc", "TOTAL_OPERATE_INCOME", inc_cols)},
                {col_or_null("inc", "DEDUCT_PARENT_NETPROFIT", inc_cols)},

                -- ── balance: 三市场共有 ──
                {col_or_null("b", "TOTAL_ASSETS", bal_cols)},
                {col_or_null("b", "TOTAL_LIABILITIES", bal_cols)},
                {col_or_null("b", "TOTAL_EQUITY", bal_cols)},
                {col_or_null("b", "TOTAL_PARENT_EQUITY", bal_cols)},
                {col_or_null("b", "FIXED_ASSET", bal_cols)},
                {col_or_null("b", "INTANGIBLE_ASSET", bal_cols)},
                {col_or_null("b", "INVENTORY", bal_cols)},
                {col_or_null("b", "ACCOUNTS_RECE", bal_cols)},
                {col_or_null("b", "SHARE_CAPITAL", bal_cols)},

                -- ── balance: 同义统一 + A 独有 ──
                {monetary},
                {col_or_null("b", "GOODWILL", bal_cols)},
                {col_or_null("b", "INDUSTRY_NAME", bal_cols, dtype="VARCHAR")},

                -- ── cashflow: 三市场共有 ──
                {col_or_null("c", "NETCASH_OPERATE", cf_cols)},
                {col_or_null("c", "NETCASH_INVEST", cf_cols)},
                {col_or_null("c", "NETCASH_FINANCE", cf_cols)},
                {col_or_null("c", "BEGIN_CCE", cf_cols)},
                {col_or_null("c", "END_CCE", cf_cols)},
                {col_or_null("c", "CCE_ADD", cf_cols)},

                -- ── cashflow: 同义统一(CAPEX / CONSTRUCT_LONG_ASSET 互为别名) ──
                {capex_expr},

                -- ── 港股通成分股标记(HK 限定 latest snapshot,A/US 恒为 FALSE) ──
                {is_hk_connect_expr}

            FROM {ind} i
            LEFT JOIN {inc} inc
              ON inc._symbol = i._symbol AND inc.REPORT_DATE = i.REPORT_DATE
            LEFT JOIN {bal} b
              ON b._symbol = i._symbol AND b.REPORT_DATE = i.REPORT_DATE
            LEFT JOIN {cf} c
              ON c._symbol = i._symbol AND c.REPORT_DATE = i.REPORT_DATE
            {hk_connect_join}
        """
        try:
            self._conn.execute(sql)
            logger.info(f"View created: {view} (4 表 LEFT JOIN + 同义字段统一)")
        except Exception as e:
            logger.warning(f"Failed to create {view}: {e}")

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

    def query_previous_close(self, market: str, symbols: tuple[str, ...], valuation_date: str) -> dict[str, float]:
        market = self._validate_market(market)
        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        frame = self.query(
            f"SELECT _symbol, close FROM v_{market.lower()}_daily WHERE _symbol IN ({placeholders}) "
            "AND CAST(date AS DATE) <= CAST(? AS DATE) "
            "QUALIFY row_number() OVER (PARTITION BY _symbol ORDER BY date DESC) = 1",
            [*symbols, valuation_date],
        )
        return {row["_symbol"]: float(row["close"]) for _, row in frame.iterrows()}

    def previous_trading_date(self, market: str, before_date: str) -> str | None:
        market = self._validate_market(market)
        frame = self.query(f"SELECT MAX(CAST(date AS DATE)) AS valuation_date FROM v_{market.lower()}_daily WHERE CAST(date AS DATE) < CAST(? AS DATE)", [before_date])
        if frame.empty or frame.iloc[0]["valuation_date"] is None:
            return None
        return str(frame.iloc[0]["valuation_date"])

    @staticmethod
    def _validate_market(market: str) -> str:
        if not isinstance(market, str):
            raise ValueError(f"unsupported market: {market}")
        normalized = market.upper()
        if normalized not in {"A", "HK", "US"}:
            raise ValueError(f"unsupported market: {market}")
        return normalized

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

    # ==================================================================
    # 冷热分层 hot-path:bundle 已加载时优先返回,业务代码无需感知
    # ------------------------------------------------------------------
    # 设计:
    # - 每个 _try_bundle_* helper 返回 Optional 结果,None 代表 miss → 走 DuckDB
    # - bundle 未加载 / market 未支持 / symbol miss → 一律降级 DuckDB
    # - 仅 4 个高频问股/K 线接口接入(K 线、周 K、分红、indicator)
    # - income/balance/cashflow/raw K 线/复权因子保持 DuckDB(bundle 暂未加载这些)
    # ==================================================================

    @staticmethod
    def _get_bundle(market: str):
        """惰性查 MarketBundle。循环 import 风险用 local import 规避。"""
        try:
            from services.backtest.data_cache import get_market

            return get_market(market)
        except Exception:  # noqa: BLE001
            return None

    def _try_bundle_qfq_kline(
        self,
        market: str,
        symbol: str,
        start: Optional[str],
        end: Optional[str],
    ) -> Optional[pd.DataFrame]:
        bundle = self._get_bundle(market)
        if bundle is None or symbol not in bundle.stock_data:
            return None
        df = bundle.stock_data[symbol]
        if df.empty:
            return None
        # 只保留 7 列,丢弃 bundle 预算的指标列
        cols = ["date", "open", "high", "low", "close", "volume", "amount"]
        out = df[cols].copy()
        if start:
            out = out[out["date"] >= start]
        if end:
            out = out[out["date"] <= end]
        return out.reset_index(drop=True)

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
        # hot-path:bundle 已加载且含此 symbol → 内存切片
        hot = self._try_bundle_qfq_kline(market, symbol, start, end)
        if hot is not None:
            return hot

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
        with self._lock:
            return self._query_qfq_kline_bulk_locked(market, symbols, start, end)

    def _query_qfq_kline_bulk_locked(
        self,
        market: str,
        symbols: Optional[list[str]],
        start: Optional[str],
        end: Optional[str],
    ) -> dict[str, pd.DataFrame]:
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
        with self._lock:
            view = f"v_{market.lower()}_daily"
            # 检查列是否存在(HK/US daily 可能没有估值列)
            cols = (
                self._conn.execute(f"DESCRIBE {view}").fetchdf()["column_name"].tolist()
            )
            val_cols = [
                c for c in ("peTTM", "pbMRQ", "psTTM", "pcfNcfTTM") if c in cols
            ]
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

    def query_index_bulk(
        self,
        market: str,
        codes: Optional[list[str]] = None,
    ) -> dict[str, pd.DataFrame]:
        """批量取指数日线序列(date 升序),code → DataFrame。

        指数无复权、无估值覆盖,直读 v_{market}_index;视图缺失返回 {}。
        codes=None 取该市场全部指数。
        """
        with self._lock:
            view = f"v_{market.lower()}_index"
            if not self._view_exists(view):
                return {}
            params: list = []
            where = ""
            if codes:
                placeholders = ",".join(["?"] * len(codes))
                where = f"WHERE _symbol IN ({placeholders})"
                params.extend(codes)
            sql = f"SELECT * FROM {view} {where} ORDER BY _symbol, date"
            df = self._conn.execute(sql, params).fetchdf()
            return self._bulk_split(df, sort_col="date")

    def query_index(
        self,
        market: str,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """查询单个指数日线(date 升序)。视图缺失返回空 DataFrame。"""
        with self._lock:
            view = f"v_{market.lower()}_index"
            if not self._view_exists(view):
                return pd.DataFrame()
            conditions = ["_symbol = ?"]
            params: list = [code]
            if start_date:
                conditions.append("date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("date <= ?")
                params.append(end_date)
            where = " AND ".join(conditions)
            sql = f"SELECT * FROM {view} WHERE {where} ORDER BY date"
            return self._conn.execute(sql, params).fetchdf()

    def query_dividend_bulk(
        self,
        market: str,
        symbols: Optional[list[str]] = None,
    ) -> dict[str, pd.DataFrame]:
        """批量取分红事件序列。视图 v_{x}_dividend 不存在时返回空 dict。"""
        with self._lock:
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

        ⚠️ 该方法返回 raw view 的**全部列**(A=176/HK=16/US=27 不对齐),
        三市场 schema 不一致。回测/strategies 应改用 query_periodic_report_bulk
        拿统一 50 列;本方法保留给需要原始列的消费者(如 DataPackBuilder
        Phase 1 数据包,某些 section 依赖 raw 拼音字段)。
        """
        with self._lock:
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

    # 业务视图层(v_{market}_periodic_report)的 fin_type → 列子集投影
    # 与 _setup_periodic_report_view 输出 50 列严格对齐;新增字段需双侧同步
    _PERIODIC_COLS = {
        "indicator": [
            # 三市场共有
            "EPSJB",
            "ROEJQ",
            "ROA",
            "ROIC",
            "BPS",
            "DILUTED_EPS",
            "XSMLL",
            "XSJLL",
            "ZCFZL",
            "LD",
            "GROSS_PROFIT_YOY",
            "OPERATE_INCOME_YOY",
            "PARENT_NETPROFIT_YOY",
            # A 股独有(HK/US 视图填 NULL,strategies 已容错)
            "PARENTNETPROFIT",
            "TOTAL_SHARE",
            "FCFF_BACK",
            "PARENTNETPROFITTZ",
        ],
        "income": [
            "PARENT_NETPROFIT",
            "NETPROFIT",
            "OPERATE_INCOME",
            "OPERATE_PROFIT",
            "TOTAL_PROFIT",
            "BASIC_EPS",
            "OPERATE_EXPENSE",
            "FINANCE_EXPENSE",
            "INCOME_TAX",
            "TOTAL_OPERATE_INCOME",
            "DEDUCT_PARENT_NETPROFIT",
        ],
        "balance": [
            "TOTAL_ASSETS",
            "TOTAL_LIABILITIES",
            "TOTAL_EQUITY",
            "TOTAL_PARENT_EQUITY",
            "FIXED_ASSET",
            "INTANGIBLE_ASSET",
            "INVENTORY",
            "ACCOUNTS_RECE",
            "SHARE_CAPITAL",
            # 同义统一 + A 独有
            "MONETARYFUNDS",
            "GOODWILL",
            "INDUSTRY_NAME",
        ],
        "cashflow": [
            "NETCASH_OPERATE",
            "NETCASH_INVEST",
            "NETCASH_FINANCE",
            "BEGIN_CCE",
            "END_CCE",
            "CCE_ADD",
            # 同义统一(双别名,strategies 现仍引用 CONSTRUCT_LONG_ASSET)
            "CAPEX",
            "CONSTRUCT_LONG_ASSET",
        ],
    }

    def query_periodic_report_bulk(
        self,
        market: str,
        symbols: Optional[list[str]] = None,
        fin_type: str = "indicator",
    ) -> dict[str, pd.DataFrame]:
        """批量取业务视图字段子集(三市场 schema 统一)。

        相对 query_financial_bulk 的差异:
        - 数据源 = v_{market}_periodic_report(4 表 LEFT JOIN + 同义统一)
        - 列输出 = _PERIODIC_COLS[fin_type] + REPORT_DATE,不含 raw 视图独有的
          冗余列(A 股 indicator 拼音指标 100+ 列等)
        - HK/US 上 A 独有字段(MONETARYFUNDS via CASH_EQUIVALENTS,CAPEX via 物理
          CAPEX,PARENTNETPROFIT NULL fill)语义已统一,strategies 透明跨市

        视图缺失或 fin_type 非法返回 {}。
        """
        if fin_type not in self._PERIODIC_COLS:
            logger.warning(f"query_periodic_report_bulk: unknown fin_type={fin_type}")
            return {}
        view = f"v_{market.lower()}_periodic_report"
        with self._lock:
            if not self._view_exists(view):
                return {}
            cols = self._PERIODIC_COLS[fin_type]
            select = ", ".join(["_symbol", "REPORT_DATE"] + cols)
            params: list = []
            where = ""
            if symbols:
                placeholders = ",".join(["?"] * len(symbols))
                where = f"WHERE _symbol IN ({placeholders})"
                params.extend(symbols)
            sql = f"SELECT {select} FROM {view} {where} ORDER BY _symbol, REPORT_DATE"
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

    # ==================================================================
    # 问股 Phase 1 数据包专用 adapter(sections 调用入口)
    # ------------------------------------------------------------------
    # 设计原则:
    #   1. 入参只要 code(带 .SH/.SZ/.HK 后缀或裸字母),market 由后缀自动推断
    #   2. SQL 内部完成字段别名 + 派生(GROSS_PROFIT / 拼音指标 → 英文别名)
    #      保持 sections 现有英文字段引用不变
    #   3. 所有 adapter 失败/视图缺失/symbol 不存在 → 返回 [] 或 None,不抛
    # ==================================================================

    @staticmethod
    def _market_of_code(code: str) -> str:
        """从 code 后缀推断市场。.SH/.SZ→A,.HK→HK,其余(纯字母)→US。"""
        upper = (code or "").upper()
        if upper.endswith((".SH", ".SZ")):
            return "A"
        if upper.endswith(".HK"):
            return "HK"
        return "US"

    # 各市场各财务表的字段映射 SQL(SELECT 子句),保留 REPORT_DATE 排序键
    # NULL::DOUBLE AS xxx 占位:视图实际无此列,sections 查 .get(key) 得 None 优雅降级
    # 三市场 schema 差异较大(EastMoney A 全字段 / EastMoney HK / EastMoney US),分开维护
    _FIN_SELECT_BY_MARKET: dict[str, dict[str, str]] = {
        "A": {
            "income": (
                "REPORT_DATE, NETPROFIT, PARENT_NETPROFIT, DEDUCT_PARENT_NETPROFIT, "
                "BASIC_EPS, OPERATE_PROFIT, OPERATE_COST, TOTAL_OPERATE_INCOME, "
                "(TOTAL_OPERATE_INCOME - TOTAL_OPERATE_COST) AS GROSS_PROFIT"
            ),
            "balance": (
                "b.REPORT_DATE, b.TOTAL_ASSETS, b.TOTAL_LIABILITIES, b.TOTAL_EQUITY, "
                "b.MONETARYFUNDS AS MONETARY_FUND, b.INVENTORY AS INVENTORIES, "
                "b.FIXED_ASSET AS FIXED_ASSETS, b.INTANGIBLE_ASSET AS INTANGIBLE_ASSETS, "
                "b.GOODWILL, b.DEBT_ASSET_RATIO, "
                "NULL::DOUBLE AS TOTAL_CURRENT_ASSETS, NULL::DOUBLE AS TOTAL_CURRENT_LIAB, "
                "i.BPS"
            ),
            "cashflow": (
                "REPORT_DATE, NETCASH_OPERATE, NETCASH_INVEST, NETCASH_FINANCE, "
                "END_CCE AS END_CASH, CONSTRUCT_LONG_ASSET, "
                "NULL::DOUBLE AS DEPRECIATION_FA"
            ),
            "indicator": (
                "REPORT_DATE, ROEJQ, ZZCJLL AS ROAJQ, "
                "XSMLL AS GROSSPROFIT_MARGIN, XSJLL AS NETPROFIT_MARGIN, "
                "ZCFZL AS DEBT_ASSET_RATIO, LD AS CURRENT_RATIO, BPS, EPSJB"
            ),
        },
        # HK schema:OPERATE_INCOME / OPERATE_EXPENSE / GROSS_PROFIT 直接给出;
        # 无 DEDUCT_PARENT_NETPROFIT;balance 无 MONETARYFUNDS(用 CASH_EQUIVALENTS)/
        # 无 INTANGIBLE_ASSET / 无 GOODWILL(中文列 HK_商誉 略过)/ 无 DEBT_ASSET_RATIO
        # (从 indicator.ZCFZL 取);cashflow 直接有 CAPEX,无 DEPRECIATION_AMORTIZATION
        "HK": {
            "income": (
                "REPORT_DATE, NETPROFIT, PARENT_NETPROFIT, "
                "NULL::DOUBLE AS DEDUCT_PARENT_NETPROFIT, "
                "BASIC_EPS, OPERATE_PROFIT, "
                "OPERATE_EXPENSE AS OPERATE_COST, "
                "OPERATE_INCOME AS TOTAL_OPERATE_INCOME, "
                "GROSS_PROFIT"
            ),
            "balance": (
                "b.REPORT_DATE, b.TOTAL_ASSETS, b.TOTAL_LIABILITIES, b.TOTAL_EQUITY, "
                "b.CASH_EQUIVALENTS AS MONETARY_FUND, b.INVENTORY AS INVENTORIES, "
                "b.FIXED_ASSET AS FIXED_ASSETS, "
                "NULL::DOUBLE AS INTANGIBLE_ASSETS, "
                "NULL::DOUBLE AS GOODWILL, "
                "i.ZCFZL AS DEBT_ASSET_RATIO, "
                "b.CURRENT_ASSETS AS TOTAL_CURRENT_ASSETS, "
                "b.CURRENT_LIABILITIES AS TOTAL_CURRENT_LIAB, "
                "i.BPS"
            ),
            "cashflow": (
                "REPORT_DATE, NETCASH_OPERATE, NETCASH_INVEST, NETCASH_FINANCE, "
                "END_CCE AS END_CASH, "
                "CAPEX AS CONSTRUCT_LONG_ASSET, "
                "NULL::DOUBLE AS DEPRECIATION_FA"
            ),
            "indicator": (
                "REPORT_DATE, ROEJQ, ROA AS ROAJQ, "
                "XSMLL AS GROSSPROFIT_MARGIN, XSJLL AS NETPROFIT_MARGIN, "
                "ZCFZL AS DEBT_ASSET_RATIO, LD AS CURRENT_RATIO, BPS, EPSJB"
            ),
        },
        # US schema:类似 HK,但 cashflow 有 DEPRECIATION_AMORTIZATION;
        # balance 有 INTANGIBLE_ASSET / GOODWILL
        "US": {
            "income": (
                "REPORT_DATE, NETPROFIT, PARENT_NETPROFIT, DEDUCT_PARENT_NETPROFIT, "
                "BASIC_EPS, OPERATE_PROFIT, "
                "OPERATE_EXPENSE AS OPERATE_COST, "
                "OPERATE_INCOME AS TOTAL_OPERATE_INCOME, "
                "GROSS_PROFIT"
            ),
            "balance": (
                "b.REPORT_DATE, b.TOTAL_ASSETS, b.TOTAL_LIABILITIES, b.TOTAL_EQUITY, "
                "b.CASH_EQUIVALENTS AS MONETARY_FUND, b.INVENTORY AS INVENTORIES, "
                "b.FIXED_ASSET AS FIXED_ASSETS, "
                "b.INTANGIBLE_ASSET AS INTANGIBLE_ASSETS, "
                "b.GOODWILL, "
                "i.ZCFZL AS DEBT_ASSET_RATIO, "
                "b.CURRENT_ASSETS AS TOTAL_CURRENT_ASSETS, "
                "b.CURRENT_LIABILITIES AS TOTAL_CURRENT_LIAB, "
                "i.BPS"
            ),
            "cashflow": (
                "REPORT_DATE, NETCASH_OPERATE, NETCASH_INVEST, NETCASH_FINANCE, "
                "END_CCE AS END_CASH, "
                "CAPEX AS CONSTRUCT_LONG_ASSET, "
                "DEPRECIATION_AMORTIZATION AS DEPRECIATION_FA"
            ),
            "indicator": (
                "REPORT_DATE, ROEJQ, ZZCJLL AS ROAJQ, "
                "XSMLL AS GROSSPROFIT_MARGIN, XSJLL AS NETPROFIT_MARGIN, "
                "ZCFZL AS DEBT_ASSET_RATIO, LD AS CURRENT_RATIO, BPS, EPSJB"
            ),
        },
    }

    def _try_bundle_financial_indicator_section(
        self, code: str, years: int
    ) -> Optional[list[dict]]:
        """问股 indicator 表 hot-path。bundle.financial_data 是 EastMoney 原 schema,
        在此处映射成 query_financial_for_section 期望的 SELECT AS 别名。"""
        market = self._market_of_code(code)
        bundle = self._get_bundle(market)
        if bundle is None or code not in bundle.financial_data:
            return None
        df = bundle.financial_data[code]
        if df.empty:
            return None
        if "REPORT_DATE" not in df.columns:
            return None
        # A 股四季度全有 → 过滤 12-31 年报;HK/US 只有年报但财年末未必 12-31 → 全保留
        if market == "A":
            annual = df[df["REPORT_DATE"].astype(str).str.endswith("-12-31")].copy()
        else:
            annual = df.copy()
        if annual.empty:
            return []
        annual = annual.sort_values("REPORT_DATE", ascending=False).head(int(years))
        # 字段映射(对齐 _FIN_SELECT["indicator"])
        out = []
        for _, row in annual.iterrows():
            out.append(
                {
                    "REPORT_DATE": row.get("REPORT_DATE"),
                    "ROEJQ": row.get("ROEJQ"),
                    "ROAJQ": row.get("ZZCJLL"),
                    "GROSSPROFIT_MARGIN": row.get("XSMLL"),
                    "NETPROFIT_MARGIN": row.get("XSJLL"),
                    "DEBT_ASSET_RATIO": row.get("ZCFZL"),
                    "CURRENT_RATIO": row.get("LD"),
                    "BPS": row.get("BPS"),
                    "EPSJB": row.get("EPSJB"),
                }
            )
        return out

    def query_financial_for_section(
        self, code: str, table: str, years: int = 5
    ) -> list[dict]:
        """问股 §3/§4/§5/§12/§13/§16 财务数据 adapter。

        - table ∈ {income, balance, cashflow, indicator, income_parent, balance_parent}
        - 取年报(REPORT_DATE 以 -12-31 结尾),REPORT_DATE 倒序最近 `years` 行
        - 字段经 SELECT AS 重命名/派生,sections 直接 .get(英文字段名) 即可
        - 视图缺失或异常 → 返回 [],sections 显示「数据缺失」
        - hot-path:table=='indicator' 且 bundle 已加载 → 内存返回(其余 table 走 DuckDB)
        """
        # 母公司表项目当前数据源未提供,直接返回空让 section 走 fallback 文案
        if table in ("income_parent", "balance_parent"):
            return []

        # hot-path:仅 indicator 表(bundle 当前只缓存这张)
        if table == "indicator":
            hot = self._try_bundle_financial_indicator_section(code, years)
            if hot is not None:
                return hot

        market = self._market_of_code(code)
        market_select = self._FIN_SELECT_BY_MARKET.get(market)
        if not market_select or table not in market_select:
            return []
        select_clause = market_select[table]
        view = f"v_{market.lower()}_{table}"
        if not self._view_exists(view):
            return []

        # A 股四季度全有(03/06/09/12)→ 用 LIKE '-12-31' 过滤年报
        # HK/US 只有年报,但财年末未必 12-31(如 01104.HK = 06-30,AAPL = 09 月)
        # → 不加日期过滤,直接 ORDER BY DESC LIMIT 取最近 N 行年报
        annual_filter_a = "AND b.REPORT_DATE LIKE '%-12-31'" if market == "A" else ""
        annual_filter = "AND REPORT_DATE LIKE '%-12-31'" if market == "A" else ""

        try:
            if table == "balance":
                # balance 需 LEFT JOIN indicator 取 BPS
                ind_view = f"v_{market.lower()}_indicator"
                ind_join = (
                    f"LEFT JOIN {ind_view} i "
                    f"ON i._symbol = b._symbol AND i.REPORT_DATE = b.REPORT_DATE"
                    if self._view_exists(ind_view)
                    else ""
                )
                # 无 indicator 视图时 i.* 字段改 NULL(BPS / DEBT_ASSET_RATIO 都来自 indicator)
                select_sql = select_clause
                if not ind_join:
                    select_sql = select_sql.replace("i.BPS", "NULL::DOUBLE AS BPS")
                    select_sql = select_sql.replace(
                        "i.ZCFZL AS DEBT_ASSET_RATIO",
                        "NULL::DOUBLE AS DEBT_ASSET_RATIO",
                    )
                sql = f"""
                    SELECT {select_sql}
                    FROM {view} b
                    {ind_join}
                    WHERE b._symbol = ?
                      {annual_filter_a}
                    ORDER BY b.REPORT_DATE DESC
                    LIMIT {int(years)}
                """
            else:
                sql = f"""
                    SELECT {select_clause}
                    FROM {view}
                    WHERE _symbol = ?
                      {annual_filter}
                    ORDER BY REPORT_DATE DESC
                    LIMIT {int(years)}
                """
            df = self._conn.execute(sql, [code]).fetchdf()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "query_financial_for_section(%s, %s) failed: %s", code, table, e
            )
            return []
        if df.empty:
            return []
        return df.to_dict("records")

    def query_qfq_kline_for_section(
        self,
        code: str,
        *,
        freq: str = "D",
        years: Optional[int] = None,
        limit: Optional[int] = None,
        order: str = "asc",
    ) -> list[dict]:
        """问股 §2/§11 K 线 adapter。

        - freq='D'(日)或 'W'(按 ISO 周聚合,周五为周末观察日)
        - years:回溯年限,自动算出 start 日期;None 则不限
        - limit + order='desc':取最近 N 根(用于 §2 取最新一根)
        - 字段:date / open / high / low / close / volume / amount(全 dict 化)
        - hot-path:bundle 已加载时,日线走 stock_data,周线走 weekly_data(已预聚合)
        """
        market = self._market_of_code(code)
        # 算 start
        start: Optional[str] = None
        if years:
            from datetime import date, timedelta

            start = (date.today() - timedelta(days=int(years) * 366)).isoformat()

        # hot-path:周线直接读 weekly_data(bundle 启动时预聚合 W-FRI),
        # 日线走 query_qfq_kline 内部 hot-path
        bundle = self._get_bundle(market)
        if bundle is not None and freq.upper() == "W" and code in bundle.weekly_data:
            wdf = bundle.weekly_data[code]
            if not wdf.empty:
                cols = [
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]
                df = wdf[cols].copy()
                if start:
                    df = df[df["date"] >= start]
                if order.lower() == "desc":
                    df = df.iloc[::-1].reset_index(drop=True)
                if limit:
                    df = df.head(int(limit))
                return df.to_dict("records")

        try:
            df = self.query_qfq_kline(market, code, start=start)
        except Exception as e:  # noqa: BLE001
            logger.warning("query_qfq_kline_for_section(%s) failed: %s", code, e)
            return []
        if df.empty:
            return []

        # 周聚合:每周取首日 open / 末日 close / max high / min low / sum volume,amount
        if freq.upper() == "W":
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = (
                df.set_index("date")
                .resample("W-FRI")
                .agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                        "amount": "sum",
                    }
                )
                .dropna(subset=["close"])
                .reset_index()
            )
            df["date"] = df["date"].dt.strftime("%Y-%m-%d")

        if order.lower() == "desc":
            df = df.iloc[::-1].reset_index(drop=True)
        if limit:
            df = df.head(int(limit))
        return df.to_dict("records")

    def query_dividend_for_section(self, code: str, years: int = 5) -> list[dict]:
        """问股 §6 每股股息 adapter。

        视图 v_{market}_dividend 按事件日存(date / cash_dividend),adapter 按
        EXTRACT(YEAR) 聚合到年并 SUM(cash_dividend) 作为 DPS。返回最近 `years` 年。
        - hot-path:bundle.dividend_data 已加载时,内存按年 groupby/sum
        """
        market = self._market_of_code(code)
        bundle = self._get_bundle(market)
        if bundle is not None and code in bundle.dividend_data:
            ddf = bundle.dividend_data[code]
            if (
                not ddf.empty
                and "date" in ddf.columns
                and "cash_dividend" in ddf.columns
            ):
                tmp = ddf[["date", "cash_dividend"]].copy()
                tmp["year"] = pd.to_datetime(tmp["date"]).dt.year.astype(int)
                grouped = (
                    tmp.groupby("year", as_index=False)["cash_dividend"]
                    .sum()
                    .rename(columns={"cash_dividend": "dps"})
                    .sort_values("year", ascending=False)
                    .head(int(years))
                )
                return grouped.to_dict("records")
        view = f"v_{market.lower()}_dividend"
        if not self._view_exists(view):
            return []
        try:
            df = self._conn.execute(
                f"""
                SELECT EXTRACT(YEAR FROM CAST(date AS DATE))::INT AS year,
                       SUM(cash_dividend) AS dps
                FROM {view}
                WHERE _symbol = ?
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT {int(years)}
                """,
                [code],
            ).fetchdf()
        except Exception as e:  # noqa: BLE001
            logger.warning("query_dividend_for_section(%s) failed: %s", code, e)
            return []
        if df.empty:
            return []
        return df.to_dict("records")

    # ---------- §7 控股股东 (EastMoney F10 + 按需拉取缓存) ----------
    @property
    def _holder_updater(self):
        """懒构造 holder updater(避免单测必须传 mock,且与 DuckDB views 解耦)。"""
        if not hasattr(self, "_holder_updater_inst"):
            try:
                from pathlib import Path

                from backend.config import DATA_DIR
                from backend.repositories.holder_repo import HolderRepository
                from backend.services.market_data.updaters.holder_updater import HolderUpdater

                holders_dir = Path(DATA_DIR) / "market" / "A" / "holders"
                self._holder_updater_inst = HolderUpdater(
                    repo=HolderRepository(holders_dir)
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("holder updater init failed: %s", e)
                self._holder_updater_inst = None
        return self._holder_updater_inst

    def query_top10_holders(self, code: str, latest_n_periods: int = 2) -> list[dict]:
        """查询十大股东最近 N 期。返回 list[dict]:每行一个 holder。"""
        upd = self._holder_updater
        if upd is None:
            return []
        try:
            records = upd.fetch_with_cache(code, "top10")
        except Exception as e:  # noqa: BLE001
            logger.warning("query_top10_holders(%s) failed: %s", code, e)
            return []
        if not records:
            return []
        # 按 END_DATE desc 取最近 N 期
        rows = [r.model_dump(exclude_none=False) for r in records]
        rows.sort(key=lambda r: str(r.get("END_DATE") or ""), reverse=True)
        end_dates = []
        for r in rows:
            ed = r.get("END_DATE")
            if ed and ed not in end_dates:
                end_dates.append(ed)
            if len(end_dates) >= latest_n_periods:
                break
        keep = set(end_dates)
        return [r for r in rows if r.get("END_DATE") in keep]

    def query_top10_free_holders(
        self, code: str, latest_n_periods: int = 2
    ) -> list[dict]:
        upd = self._holder_updater
        if upd is None:
            return []
        try:
            records = upd.fetch_with_cache(code, "top10_free")
        except Exception as e:  # noqa: BLE001
            logger.warning("query_top10_free_holders(%s) failed: %s", code, e)
            return []
        if not records:
            return []
        rows = [r.model_dump(exclude_none=False) for r in records]
        rows.sort(key=lambda r: str(r.get("END_DATE") or ""), reverse=True)
        end_dates = []
        for r in rows:
            ed = r.get("END_DATE")
            if ed and ed not in end_dates:
                end_dates.append(ed)
            if len(end_dates) >= latest_n_periods:
                break
        keep = set(end_dates)
        return [r for r in rows if r.get("END_DATE") in keep]

    def query_holder_count(self, code: str) -> list[dict]:
        """股东户数 — 当期 + PRE_END_DATE 上期(self-contained 单条记录)。"""
        upd = self._holder_updater
        if upd is None:
            return []
        try:
            records = upd.fetch_with_cache(code, "holder_count")
        except Exception as e:  # noqa: BLE001
            logger.warning("query_holder_count(%s) failed: %s", code, e)
            return []
        if not records:
            return []
        rows = [r.model_dump(exclude_none=False) for r in records]
        rows.sort(key=lambda r: str(r.get("END_DATE") or ""), reverse=True)
        return rows

    def query_circulating_shares_for_section(self, code: str) -> Optional[int]:
        """问股 §2 流通股数 adapter — 读 meta/circulating_shares.parquet。

        symbol 字段是裸 6 位数字(无后缀),A 股 code 截前 6 位匹配;HK/US 暂无数据。
        文件不存在或 symbol 不匹配 → None。
        """
        try:
            from services.market_data.updaters.circulating_shares import get_circulating_shares

            df = get_circulating_shares()
        except Exception as e:  # noqa: BLE001
            logger.warning("get_circulating_shares failed: %s", e)
            return None
        if df is None or df.empty:
            return None
        # A 股 code = '002594.SZ' → '002594'
        bare = code.split(".")[0]
        hit = df[df["symbol"] == bare]
        if hit.empty:
            return None
        try:
            return int(hit.iloc[0]["circulating_shares"])
        except Exception:  # noqa: BLE001
            return None

    def query_total_shares_for_section(self, code: str) -> Optional[int]:
        """问股 §17 总股本 adapter — 多市场:

        - A 股:`v_a_indicator.TOTAL_SHARE` 最新一期(EastMoney 财务指标 schema)
        - 美股:`v_us_balance.COMMON_STOCK_SHARES` 最新一期(yfinance / EastMoney US)
        - 港股:indicator 表无 TOTAL_SHARE 列 → 用最新年报
                `income.PARENT_NETPROFIT / income.BASIC_EPS` 倒推
                (与 strategies/utils/conservative.py:175 fallback 一致)

        与 query_circulating_shares_for_section 不同:这里取总股本(含限售),
        用于市值/EV 计算;前者取流通 A 股(A_FREE_SHARE)。
        视图缺失/无数据 → None。
        """
        market = self._market_of_code(code)
        try:
            if market == "A":
                view = f"v_a_indicator"
                if not self._view_exists(view):
                    return None
                df = self._conn.execute(
                    f"""
                    SELECT TOTAL_SHARE
                    FROM {view}
                    WHERE _symbol = ? AND TOTAL_SHARE IS NOT NULL AND TOTAL_SHARE > 0
                    ORDER BY REPORT_DATE DESC
                    LIMIT 1
                    """,
                    [code],
                ).fetchdf()
                if df.empty:
                    return None
                return int(df.iloc[0]["TOTAL_SHARE"])

            if market == "US":
                view = "v_us_balance"
                if not self._view_exists(view):
                    return None
                df = self._conn.execute(
                    f"""
                    SELECT COMMON_STOCK_SHARES
                    FROM {view}
                    WHERE _symbol = ?
                      AND COMMON_STOCK_SHARES IS NOT NULL
                      AND COMMON_STOCK_SHARES > 0
                    ORDER BY REPORT_DATE DESC
                    LIMIT 1
                    """,
                    [code],
                ).fetchdf()
                if df.empty:
                    return None
                return int(df.iloc[0]["COMMON_STOCK_SHARES"])

            if market == "HK":
                view = "v_hk_income"
                if not self._view_exists(view):
                    return None
                # 取最新有 PARENT_NETPROFIT + BASIC_EPS 且 EPS > 0 的年报
                df = self._conn.execute(
                    f"""
                    SELECT PARENT_NETPROFIT, BASIC_EPS
                    FROM {view}
                    WHERE _symbol = ?
                      AND PARENT_NETPROFIT IS NOT NULL
                      AND BASIC_EPS IS NOT NULL
                      AND BASIC_EPS > 0
                      AND PARENT_NETPROFIT > 0
                    ORDER BY REPORT_DATE DESC
                    LIMIT 1
                    """,
                    [code],
                ).fetchdf()
                if df.empty:
                    return None
                np_v = float(df.iloc[0]["PARENT_NETPROFIT"])
                eps = float(df.iloc[0]["BASIC_EPS"])
                if eps <= 0:
                    return None
                return int(np_v / eps)
        except Exception as e:  # noqa: BLE001
            logger.warning("query_total_shares_for_section(%s) failed: %s", code, e)
            return None
        return None

    def query_latest_report_date(self, code: str) -> Optional[str]:
        """问股定性分析 cache 失效用 — 取 v_<market>_indicator 中该股票最新 REPORT_DATE。

        视图缺失 / 无数据 / 异常 → None,调用方按"无失效校验,只跑 TTL"降级。
        返回格式:'YYYY-MM-DD' 字符串(与 cache 内 report_date 字段对齐)。
        """
        market = self._market_of_code(code)
        view = f"v_{market.lower()}_indicator"
        if not self._view_exists(view):
            return None
        try:
            df = self._conn.execute(
                f"""
                SELECT MAX(REPORT_DATE) AS latest
                FROM {view}
                WHERE _symbol = ? AND REPORT_DATE IS NOT NULL
                """,
                [code],
            ).fetchdf()
        except Exception as e:  # noqa: BLE001
            logger.warning("query_latest_report_date(%s) failed: %s", code, e)
            return None
        if df.empty or df.iloc[0]["latest"] is None:
            return None
        return str(df.iloc[0]["latest"])

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
