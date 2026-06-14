"""股票代码索引服务 — 从 parquet 文件名和 stock_list 构建内存索引，支持前缀搜索"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from config import MARKET_DIR

logger = logging.getLogger(__name__)

# A 股代码索引源:与 HK/US 的 data/market/<mkt>/stock_list.* 对齐,
# 统一收口到 data/market/A/(旧路径 data/basic/A/ 已废弃)
A_INDEX_DIR = MARKET_DIR / "A"


@dataclass
class StockIndexEntry:
    code: str
    name: Optional[str]
    market: str  # "A", "HK", "US"
    industry: Optional[str] = None


_index: List[StockIndexEntry] = []


def _load_hk_name_map() -> dict:
    """读 data/market/HK/stock_list.csv → {code: name}。

    标准 CSV(code,name 两列),标准 pandas.read_csv 即可。
    文件不存在或解析失败返回空 dict(降级)。
    """
    path = MARKET_DIR / "HK" / "stock_list.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception as e:
        logger.warning("读取 HK stock_list.csv 失败: %s", e)
        return {}
    out: dict = {}
    for _, row in df.iterrows():
        code = row.get("code")
        name = row.get("name")
        if code:
            out[code] = (
                name
                if name and not (isinstance(name, float) and pd.isna(name))
                else None
            )
    return out


def _load_us_name_map() -> dict:
    """读 data/market/US/stock_list.csv → {ticker: name}。

    schema: ticker,cik,name —— ⚠️ name 字段含逗号但无引号(如 "Tesla, Inc."),
    pandas.read_csv 会因列数不匹配报错;手动按 split(',', 2) 解析最稳妥。
    """
    path = MARKET_DIR / "US" / "stock_list.csv"
    if not path.exists():
        return {}
    out: dict = {}
    try:
        with path.open(encoding="utf-8") as f:
            next(f, None)  # skip header
            for line in f:
                parts = line.rstrip("\n").split(
                    ",", 2
                )  # ticker / cik / rest(含逗号的 name)
                if len(parts) == 3:
                    ticker, _cik, name = parts
                    if ticker:
                        out[ticker] = name or None
    except Exception as e:
        logger.warning("读取 US stock_list.csv 失败: %s", e)
        return {}
    return out


def _load_hk_industry_map() -> dict:
    """读 data/market/HK/membership/hk_industry.parquet → {code: {name, sector, industry}}。

    parquet 不存在或读取失败 → 返回空 dict(降级,不阻塞索引构建)。
    """
    path = MARKET_DIR / "HK" / "membership" / "hk_industry.parquet"
    if not path.exists():
        return {}
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        logger.warning("读取 hk_industry.parquet 失败: %s", e)
        return {}
    out: dict = {}
    for _, row in df.iterrows():
        code = str(row["code"])
        ind = row.get("industry")
        if ind is not None and isinstance(ind, float) and pd.isna(ind):
            ind = None
        sec = row.get("sector")
        if sec is not None and isinstance(sec, float) and pd.isna(sec):
            sec = None
        nm = row.get("name")
        if nm is not None and isinstance(nm, float) and pd.isna(nm):
            nm = None
        out[code] = {"name": nm, "sector": sec, "industry": ind}
    return out


def refresh_hk_industry() -> None:
    """hk_industry.parquet 写入后调用,把 industry 回填到内存索引。
    避免重启服务才能看到新数据。

    name 已在 init 时从 stock_list.csv 全覆盖加载,这里只负责更新 industry,
    必要时也用 hk_industry.parquet 的 name 兜底(stock_list 缺时)。"""
    global _index
    if not _index:
        return
    hk_industry_map = _load_hk_industry_map()
    if not hk_industry_map:
        return
    for i, e in enumerate(_index):
        if e.market != "HK":
            continue
        rec = hk_industry_map.get(e.code)
        if rec is None:
            continue
        _index[i] = StockIndexEntry(
            code=e.code,
            name=e.name or rec.get("name"),
            market="HK",
            industry=rec.get("industry") or e.industry,
        )
    logger.info("港股 industry 内存索引已刷新: %d 条", len(hk_industry_map))


def init_stock_index() -> None:
    """启动时构建索引：从文件名加载代码，A股额外加载名称"""
    global _index
    entries: List[StockIndexEntry] = []

    # A股：从 stock_list.parquet 加载 code+name
    a_list_path = A_INDEX_DIR / "stock_list.parquet"
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

    # 港股 — 主索引来自 daily 文件名,name 来自 stock_list.csv(全覆盖),
    # industry/sector 来自 hk_industry.parquet(仅港股通子集,可选)
    hk_name_map = _load_hk_name_map()
    hk_industry_map = _load_hk_industry_map()
    hk_dir = MARKET_DIR / "HK" / "daily"
    hk_count = 0
    hk_with_name = 0
    if hk_dir.exists():
        for f in hk_dir.glob("*.parquet"):
            ind_rec = hk_industry_map.get(f.stem)
            # name 优先级:stock_list.csv > hk_industry.parquet
            name = hk_name_map.get(f.stem) or (ind_rec.get("name") if ind_rec else None)
            if name:
                hk_with_name += 1
            entries.append(
                StockIndexEntry(
                    code=f.stem,
                    name=name,
                    market="HK",
                    industry=ind_rec.get("industry") if ind_rec else None,
                )
            )
            hk_count += 1
    logger.info(
        "港股索引加载完成: %d 只 (带 name: %d, 带 industry: %d)",
        hk_count,
        hk_with_name,
        len(hk_industry_map),
    )

    # 美股 — 主索引来自 daily 文件名,name 来自 stock_list.csv
    us_name_map = _load_us_name_map()
    us_dir = MARKET_DIR / "US" / "daily"
    us_count = 0
    us_with_name = 0
    if us_dir.exists():
        for f in us_dir.glob("*.parquet"):
            name = us_name_map.get(f.stem)
            if name:
                us_with_name += 1
            entries.append(StockIndexEntry(code=f.stem, name=name, market="US"))
            us_count += 1
    logger.info("美股索引加载完成: %d 只 (带 name: %d)", us_count, us_with_name)

    _index = entries
    logger.info("股票索引总计: %d 条", len(_index))


def _infer_market(code: str) -> Optional[str]:
    """从 code 后缀推断 market;纯字母视为 US。无法识别返回 None。"""
    upper = code.upper()
    if upper.endswith((".SH", ".SZ")):
        return "A"
    if upper.endswith(".HK"):
        return "HK"
    if upper.replace("-", "").replace(".", "").isalpha():
        return "US"
    return None


def get_name(code: str, market: Optional[str] = None) -> Optional[str]:
    """根据 code 查名称。market 不传时按 code 后缀自动推断。

    传 market 仍然支持(向后兼容,显式过滤);默认行为改为后缀路由,
    解决 extract() 不传 market 导致 HK/US 查不到的问题。
    """
    if market is None:
        market = _infer_market(code)
    for e in _index:
        if e.code == code and (market is None or e.market == market):
            return e.name
    return None


def get_industry(code: str, market: Optional[str] = None) -> Optional[str]:
    """根据 code 查行业(证监会分类)。market 不传时按 code 后缀自动推断。"""
    if market is None:
        market = _infer_market(code)
    for e in _index:
        if e.code == code and (market is None or e.market == market):
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
