"""流通股数快照服务 — 从 DuckDB v_a_indicator.A_FREE_SHARE 取数(2026-05-24 重构)。

数据来源:EastMoney 财务指标(已经在 `data/market/A/financial/indicator/` 落盘),
DuckDB 视图 `v_a_indicator` 暴露 `TOTAL_SHARE / A_FREE_SHARE / B_FREE_SHARE` 列。
本服务遍历最新一期报告,取每只股票的 `A_FREE_SHARE`(A 股流通股),
落盘为 `meta/circulating_shares.parquet`(schema 与原 akshare 版兼容)。

旧版本依赖 akshare `stock_zh_a_spot_em`(用流通市值 / 最新价反算),不稳定,已废弃。
"""

import logging
from datetime import date

import pandas as pd

from config import META_DIR
from repositories.base import check_write_integrity

logger = logging.getLogger(__name__)

CIRCULATING_SHARES_FILE = META_DIR / "circulating_shares.parquet"


def update_circulating_shares(on_phase: callable = None) -> dict:
    """从 DuckDB v_a_indicator 取每只 A 股最新一期的 A_FREE_SHARE,落 parquet。

    返回: {"count": N, "update_date": "YYYY-MM-DD"}
    """

    def _phase(msg):
        if on_phase:
            on_phase(msg)

    # 延迟 import,避免单测因 DuckDB 初始化重型依赖而启动慢
    from services.market_data.duckdb_store import get_store

    logger.info("开始从 DuckDB v_a_indicator 抽取流通股数...")
    _phase("查询 DuckDB v_a_indicator...")

    store = get_store()
    # 每只股票取最新一期(REPORT_DATE 最大)的 A_FREE_SHARE
    sql = """
    WITH ranked AS (
        SELECT
            SECURITY_CODE,
            REPORT_DATE,
            A_FREE_SHARE,
            ROW_NUMBER() OVER (PARTITION BY SECURITY_CODE ORDER BY REPORT_DATE DESC) AS rn
        FROM v_a_indicator
        WHERE A_FREE_SHARE IS NOT NULL AND A_FREE_SHARE > 0
    )
    SELECT SECURITY_CODE, A_FREE_SHARE
    FROM ranked
    WHERE rn = 1
    """
    df = store._conn.execute(sql).fetchdf()
    _phase(f"DuckDB 返回 {len(df)} 条记录...")

    if df.empty:
        raise ValueError(
            "v_a_indicator.A_FREE_SHARE 没有可用数据,请先跑 financial_updater"
        )

    # 标准化为 6 位代码字符串(去掉 .SH/.SZ/.BJ 后缀)
    df["symbol"] = df["SECURITY_CODE"].astype(str).str.zfill(6)
    df["circulating_shares"] = df["A_FREE_SHARE"].round(0).astype("int64")

    today = date.today().isoformat()
    df["update_date"] = today

    result = (
        df[["symbol", "circulating_shares", "update_date"]]
        .drop_duplicates(subset=["symbol"])
        .reset_index(drop=True)
    )
    _phase(f"保存 {len(result)} 只股票数据...")
    # 重算型快照: 流通股随报告期变动属合法, 仅护结构 + 灾难性骤减(如 v_a_indicator
    # 半拉子导致全市场股票数腰斩), 违规 raise 中止, 保留旧快照。
    check_write_integrity(
        CIRCULATING_SHARES_FILE, result, key="symbol", mode="recompute"
    )
    result.to_parquet(CIRCULATING_SHARES_FILE, index=False)

    logger.info(
        "流通股数保存完成: %d 只股票, 日期=%s, 来源=v_a_indicator", len(result), today
    )
    return {"count": len(result), "update_date": today}


def get_circulating_shares() -> pd.DataFrame | None:
    """读取已保存的流通股数快照,返回 DataFrame 或 None。"""
    if not CIRCULATING_SHARES_FILE.exists():
        return None
    return pd.read_parquet(CIRCULATING_SHARES_FILE)
