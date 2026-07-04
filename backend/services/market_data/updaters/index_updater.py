"""指数数据更新器 —— 维护 data/market/{market}/index/ 下的指数日线。

指数(HSI / 恒生科技 / 沪深300 等)是独立于个股的一类数据:
- **不需要复权因子**(指数本身无分红/拆股口径,价格序列连续)
- **不进股票 universe**(独立目录/视图,绝不会被 query_qfq_kline_bulk 当成可买持仓)
- 主要用途:回测市场择时 regime、equity-curve 基准对比、相对强弱因子

落点:data/market/{market}/index/{code}.parquet,schema 复用 daily 7 列
(date/open/high/low/close/volume/amount + 可选 preclose/pctChg)。

数据源(遵循数据源铁律,只用 baostock / yfinance):
- HSI / HSTECH:yfinance(^HSI / ^HSTECH)
- 沪深300:baostock(sh.000300,指数 k-data 字段集比个股窄)
"""

from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from backend.config import MARKET_DIR
from backend.models.market import DailyKlineRecord
from backend.repositories.base import (
    IntegrityPolicy,
    append_models_to_parquet,
    write_models_as_parquet,
)

# 指数 K 线台账型(同日 K 线): 历史 bar 不可 null/删除。
_INDEX_INTEGRITY = IntegrityPolicy(key="date", mode="ledger")

logger = logging.getLogger(__name__)

# 指数全量起始日期(与 HK GARP 回测区间对齐)
DEFAULT_START = "2010-01-01"


# ---------------- 指数清单 ----------------
# code   : 落库文件名 / DuckDB _symbol(干净标识,不带 yf 的 ^ 或 bs 的 sh. 前缀)
# market : 归属市场分区(决定落点 data/market/{market}/index/ 与视图 v_{m}_index)
# source : yfinance | baostock
# src    : 数据源原始代码(yfinance 的 ^HSI / baostock 的 sh.000300)
INDEX_CATALOG: List[dict] = [
    {"code": "HSI", "market": "HK", "source": "yfinance", "src": "^HSI",
     "name": "恒生指数"},
    {"code": "CSI300", "market": "A", "source": "baostock", "src": "sh.000300",
     "name": "沪深300"},
    # ⚠️ 恒生科技指数(HSTECH):yfinance 无 ^HSTECH(404),baostock 不含港股指数。
    #    该指数 2020-07 才推出,对 2010-2026 全期回测的市场 regime 用处有限。
    #    若需要,可改用 ETF 3033.HK(iShares 恒生科技 ETF)作可交易代理,但
    #    ETF 含分红噪声且仅 2020 起,需单独评估,暂不纳入纯指数清单。
]

# baostock 指数 k-data 支持的字段(比个股窄:无 turn/peTTM/isST 等)
_BS_INDEX_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,pctChg"


def _index_dir(market: str):
    return MARKET_DIR / market / "index"


def _index_path(market: str, code: str):
    return _index_dir(market) / f"{code}.parquet"


def get_index_catalog() -> List[dict]:
    """对外暴露指数清单(浅拷贝,防外部篡改)。"""
    return [dict(item) for item in INDEX_CATALOG]


# ---------------- 数据源抓取 ----------------


def _fetch_yfinance_index(
    src_symbol: str, code: str, start_date: Optional[str]
) -> List[DailyKlineRecord]:
    """用 yfinance 抓指数日线。start_date=None → period='max' 全量。"""
    import yfinance as yf

    t = yf.Ticker(src_symbol)
    if start_date:
        df = t.history(start=start_date, auto_adjust=False)
    else:
        df = t.history(period="max", auto_adjust=False)

    if df.empty:
        return []

    records: List[DailyKlineRecord] = []
    prev_close: Optional[float] = None
    for idx, row in df.iterrows():
        close = float(row["Close"])
        volume = float(row["Volume"]) if pd.notna(row.get("Volume")) else 0.0
        data = {
            "date": idx.strftime("%Y-%m-%d"),
            "code": code,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": close,
            "volume": volume,
            "amount": 0.0,
        }
        if prev_close is not None and prev_close > 0:
            data["preclose"] = prev_close
            data["pctChg"] = (close - prev_close) / prev_close * 100
        prev_close = close
        records.append(DailyKlineRecord(**data))
    return records


def _fetch_baostock_index(
    src_symbol: str, code: str, start_date: Optional[str]
) -> List[DailyKlineRecord]:
    """用 baostock 抓指数日线(指数字段集比个股窄,单独取)。"""
    import baostock as bs

    from backend.adapters.baostock_adapter import _result_to_df

    lg = bs.login()
    try:
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login failed: {lg.error_msg}")
        rs = bs.query_history_k_data_plus(
            src_symbol,
            _BS_INDEX_FIELDS,
            start_date=start_date or DEFAULT_START,
            frequency="d",
        )
        df = _result_to_df(rs)
    finally:
        bs.logout()

    if df.empty:
        return []

    num_cols = ["open", "high", "low", "close", "preclose", "volume", "amount", "pctChg"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    records: List[DailyKlineRecord] = []
    for _, row in df.iterrows():
        data = {
            "date": str(row["date"]),
            "code": code,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if pd.notna(row.get("volume")) else 0.0,
            "amount": float(row["amount"]) if pd.notna(row.get("amount")) else 0.0,
        }
        if pd.notna(row.get("preclose")):
            data["preclose"] = float(row["preclose"])
        if pd.notna(row.get("pctChg")):
            data["pctChg"] = float(row["pctChg"])
        records.append(DailyKlineRecord(**data))
    return records


def _fetch_index(item: dict, start_date: Optional[str]) -> List[DailyKlineRecord]:
    if item["source"] == "yfinance":
        return _fetch_yfinance_index(item["src"], item["code"], start_date)
    if item["source"] == "baostock":
        return _fetch_baostock_index(item["src"], item["code"], start_date)
    raise ValueError(f"未知指数数据源: {item['source']}")


# ---------------- 落库 ----------------


def _latest_date(market: str, code: str) -> Optional[str]:
    path = _index_path(market, code)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["date"])
        if df.empty:
            return None
        return str(df["date"].max())
    except Exception:
        return None


def update_index(item: dict, full: bool = False) -> dict:
    """更新单个指数。full=True 全量重抓;否则从最新日期增量。

    返回 {code, market, written, mode, error?}。
    """
    code, market = item["code"], item["market"]
    result = {"code": code, "market": market, "written": 0, "mode": "full"}
    try:
        start: Optional[str] = None
        if not full:
            latest = _latest_date(market, code)
            if latest:
                start = latest  # 包含最新日,append 去重覆盖当日 partial bar
                result["mode"] = "incremental"

        records = _fetch_index(item, start)
        if not records:
            logger.info("index %s: 无新数据 (start=%s)", code, start)
            return result

        path = _index_path(market, code)
        if full or not path.exists():
            # date 降序,与 daily 约定一致
            write_models_as_parquet(
                path, records, sort_by="date", ascending=False,
                integrity=_INDEX_INTEGRITY,
            )
        else:
            append_models_to_parquet(
                path, records, DailyKlineRecord,
                dedup_key="date", sort_by="date", ascending=False,
                integrity=_INDEX_INTEGRITY,
            )
        result["written"] = len(records)
        logger.info("index %s: 写入 %d 条 (%s)", code, len(records), result["mode"])
    except Exception as e:
        logger.exception("index %s 更新失败: %s", code, e)
        result["error"] = str(e)
    return result


def update_all_indices(full: bool = False) -> List[dict]:
    """更新清单内全部指数,更新后刷新 DuckDB 视图。"""
    results = [update_index(item, full=full) for item in INDEX_CATALOG]

    # 落库后刷新视图,业务侧立即可查
    try:
        from backend.services.market_data.duckdb_store import get_store

        store = get_store()
        for market in {item["market"] for item in INDEX_CATALOG}:
            store.refresh_index_view(market)
    except Exception as e:
        logger.warning("刷新指数视图失败(不影响落库): %s", e)

    return results
