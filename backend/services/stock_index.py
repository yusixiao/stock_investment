"""股票代码索引服务 — 从 parquet 文件名和 stock_list 构建内存索引，支持前缀搜索"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from config import DATA_DIR, MARKET_DIR

logger = logging.getLogger(__name__)

BASIC_DIR = DATA_DIR / "basic" / "A"


@dataclass
class StockIndexEntry:
    code: str
    name: Optional[str]
    market: str  # "A", "HK", "US"


_index: List[StockIndexEntry] = []


def init_stock_index() -> None:
    """启动时构建索引：从文件名加载代码，A股额外加载名称"""
    global _index
    entries: List[StockIndexEntry] = []

    # A股：从 stock_list.parquet 加载 code+name
    a_list_path = BASIC_DIR / "stock_list.parquet"
    if a_list_path.exists():
        df = pd.read_parquet(a_list_path, columns=["code", "name", "status"])
        # status=1 表示正常上市
        active = df[df["status"] == "1"]
        for _, row in active.iterrows():
            entries.append(
                StockIndexEntry(
                    code=row["code"],
                    name=row["name"],
                    market="A",
                )
            )
        logger.info("A股索引加载完成: %d 只", len(entries))
    else:
        # fallback：从 daily 文件名
        a_dir = MARKET_DIR / "A" / "daily"
        if a_dir.exists():
            for f in a_dir.glob("*.parquet"):
                entries.append(StockIndexEntry(code=f.stem, name=None, market="A"))
            logger.info(
                "A股索引(文件名): %d 只", sum(1 for e in entries if e.market == "A")
            )

    # 港股
    hk_dir = MARKET_DIR / "HK" / "daily"
    hk_count = 0
    if hk_dir.exists():
        for f in hk_dir.glob("*.parquet"):
            entries.append(StockIndexEntry(code=f.stem, name=None, market="HK"))
            hk_count += 1
    logger.info("港股索引加载完成: %d 只", hk_count)

    # 美股
    us_dir = MARKET_DIR / "US" / "daily"
    us_count = 0
    if us_dir.exists():
        for f in us_dir.glob("*.parquet"):
            entries.append(StockIndexEntry(code=f.stem, name=None, market="US"))
            us_count += 1
    logger.info("美股索引加载完成: %d 只", us_count)

    _index = entries
    logger.info("股票索引总计: %d 条", len(_index))


def search_stocks(query: str, limit: int = 10) -> List[dict]:
    """前缀搜索：数字开头匹配A股/港股代码，字母开头匹配美股代码"""
    if not query:
        return []

    q = query.strip().upper()
    results: List[dict] = []

    is_digit = q[0].isdigit()

    for entry in _index:
        if is_digit:
            if entry.market in ("A", "HK"):
                code_num = entry.code.split(".")[0] if "." in entry.code else entry.code
                if code_num.startswith(q):
                    results.append(
                        {
                            "code": entry.code,
                            "name": entry.name,
                            "market": entry.market,
                        }
                    )
        else:
            if entry.market == "US":
                if entry.code.upper().startswith(q):
                    results.append(
                        {
                            "code": entry.code,
                            "name": entry.name,
                            "market": entry.market,
                        }
                    )

    results.sort(key=lambda r: r["code"])
    return results[:limit]
