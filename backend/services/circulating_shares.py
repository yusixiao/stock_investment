"""流通股数快照服务 — 从 stock_zh_a_spot_em 获取流通市值并反算流通股数。"""

import logging
from datetime import date

import akshare as ak
import pandas as pd

from config import META_DIR

logger = logging.getLogger(__name__)

CIRCULATING_SHARES_FILE = META_DIR / "circulating_shares.parquet"


def update_circulating_shares() -> dict:
    """调用 stock_zh_a_spot_em 获取全部 A 股实时行情，计算流通股数并保存。

    流通股数 = 流通市值 / 最新价
    返回: {"count": N, "update_date": "YYYY-MM-DD"}
    """
    logger.info("开始获取流通股数数据...")
    df = ak.stock_zh_a_spot_em()

    # 提取需要的列：代码、最新价、流通市值
    required_cols = {"代码", "最新价", "流通市值"}
    if not required_cols.issubset(set(df.columns)):
        raise ValueError(f"API 返回缺少必要列，当前列: {df.columns.tolist()}")

    df = df[["代码", "最新价", "流通市值"]].copy()
    df.columns = ["symbol", "price", "circulating_mv"]

    # 过滤无效数据（价格或流通市值为 0/NaN）
    df = df.dropna(subset=["price", "circulating_mv"])
    df = df[(df["price"] > 0) & (df["circulating_mv"] > 0)]

    # 计算流通股数（单位：股）
    df["circulating_shares"] = (df["circulating_mv"] / df["price"]).round(0).astype(int)

    today = date.today().isoformat()
    df["update_date"] = today

    result = df[["symbol", "circulating_shares", "update_date"]].reset_index(drop=True)
    result.to_parquet(CIRCULATING_SHARES_FILE, index=False)

    logger.info("流通股数保存完成: %d 只股票, 日期=%s", len(result), today)
    return {"count": len(result), "update_date": today}


def get_circulating_shares() -> pd.DataFrame | None:
    """读取已保存的流通股数快照，返回 DataFrame 或 None。"""
    if not CIRCULATING_SHARES_FILE.exists():
        return None
    return pd.read_parquet(CIRCULATING_SHARES_FILE)
