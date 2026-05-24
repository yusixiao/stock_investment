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
    industry: Optional[str] = None


_index: List[StockIndexEntry] = []


def init_stock_index() -> None:
    """启动时构建索引：从文件名加载代码，A股额外加载名称"""
    global _index
    entries: List[StockIndexEntry] = []

    # A股：从 stock_list.parquet 加载 code+name
    a_list_path = BASIC_DIR / "stock_list.parquet"
    if a_list_path.exists():
        # 兼容旧 parquet 无 industry 列的情况
        try:
            df = pd.read_parquet(
                a_list_path, columns=["code", "name", "status", "industry"]
            )
        except (KeyError, ValueError):
            df = pd.read_parquet(a_list_path, columns=["code", "name", "status"])
            df["industry"] = None
        # status=1 表示正常上市
        active = df[df["status"] == "1"]
        for _, row in active.iterrows():
            ind = row.get("industry") if "industry" in row.index else None
            if ind is not None and (isinstance(ind, float) and pd.isna(ind)):
                ind = None
            entries.append(
                StockIndexEntry(
                    code=row["code"],
                    name=row["name"],
                    market="A",
                    industry=ind,
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


def get_name(code: str, market: str = "A") -> Optional[str]:
    """根据 (code, market) 查名称。索引未命中返回 None。"""
    for e in _index:
        if e.code == code and e.market == market:
            return e.name
    return None


def get_industry(code: str, market: str = "A") -> Optional[str]:
    """根据 (code, market) 查行业(证监会分类)。索引未命中或 industry 缺失返回 None。"""
    for e in _index:
        if e.code == code and e.market == market:
            return e.industry
    return None


def get_peers_by_industry(
    industry: str,
    exclude_code: Optional[str] = None,
    limit: int = 5,
    market: str = "A",
) -> List[StockIndexEntry]:
    """返回同行业的索引条目(排除指定 code,默认前 limit 个,按 code 字典序)。

    industry 缺失或匹配不到任何条目时返回空列表。
    """
    if not industry:
        return []
    peers = [
        e
        for e in _index
        if e.market == market and e.industry == industry and e.code != exclude_code
    ]
    peers.sort(key=lambda e: e.code)
    return peers[:limit]


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
