"""港股 sector/industry updater — yfinance 拉 .info,落 parquet。

数据落点(AGENTS.md 铁律 — 业务数据必须落 data/market/):
  data/market/HK/membership/hk_industry.parquet

schema:
  code        str  5 位 HK 代码(带前导 0,如 "09988")
  name        str  longName(yfinance,英文)
  sector      str  yfinance.info.sector(如 "Technology")
  industry    str  yfinance.info.industry(如 "Internet Retail")
  updated_at  str  ISO datetime,本次抓取时间(UTC)

去重键:code(同一只股票只保留最新一条)

策略:
  - 默认覆盖范围 = 港股通成分股最新名单(get_latest_hk_connect_codes())
  - 增量:已存在且 updated_at 在 max_age_days 内的 code 跳过
  - 失败容忍:per-code try/except,单只失败不阻塞整体
  - 限速:每只之间 sleep 0.5s(yfinance 公开接口易限速)

⚠️ yfinance 公开 API 不稳定,大批量(数百只)单次跑批可能耗时 10-30 分钟,
   且部分股票 .info 可能返回空 dict / 缺 sector 字段,需容错。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from backend.config import MARKET_DIR
from backend.repositories.base import check_write_integrity
from backend.services.market_data.updaters.hk_connect_updater import get_latest_hk_connect_codes

logger = logging.getLogger(__name__)


def _parquet_path() -> Path:
    """港股 industry parquet 路径。"""
    p = MARKET_DIR / "HK" / "membership" / "hk_industry.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _to_yfinance_symbol(code: str) -> str:
    """5 位 HK 代码 -> yfinance 4 位代码 + .HK 后缀。

    "09988" -> "9988.HK"
    "00700" -> "0700.HK"
    "0700.HK" -> "0700.HK"(已带后缀直接返回)
    """
    if "." in code:
        return code.upper()
    s = code.strip()
    # 取最后 4 位(yfinance 用 4 位数字)
    if len(s) >= 4:
        s = s[-4:]
    return f"{s}.HK"


def _fetch_one(code: str) -> dict | None:
    """单只港股拉取 sector/industry。

    Returns:
        {"code": code, "name": str, "sector": str|None, "industry": str|None}
        失败返回 None。
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("hk_industry_updater: yfinance 未安装")
        return None

    yf_sym = _to_yfinance_symbol(code)
    try:
        t = yf.Ticker(yf_sym)
        info = t.info or {}
    except Exception as e:
        logger.warning("hk_industry_updater: %s 拉取失败: %s", yf_sym, e)
        return None

    if not info:
        return None

    sector = info.get("sector")
    industry = info.get("industry")
    name = info.get("longName") or info.get("shortName")
    # sector 和 industry 都缺 -> 视为无效数据(yfinance 偶尔返回空壳 info)
    if not sector and not industry:
        return None

    return {
        "code": code,
        "name": name,
        "sector": sector,
        "industry": industry,
    }


def fetch_and_save_hk_industry(
    codes: Iterable[str] | None = None,
    *,
    max_age_days: int = 30,
    sleep_sec: float = 0.5,
    fetch_one_func=None,
) -> dict:
    """拉取港股 sector/industry 并增量更新 parquet。

    Args:
        codes: 待更新的 5 位 HK 代码集合;None 则用最新港股通名单
        max_age_days: 已有记录在此天数内视为新鲜,跳过
        sleep_sec: 每只之间的限速间隔(秒)
        fetch_one_func: 注入点,测试用;默认 _fetch_one

    Returns:
        {"fetched": int, "skipped": int, "failed": int, "total_rows": int, "path": str}
    """
    fetch = fetch_one_func or _fetch_one
    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_iso = now.isoformat()

    if codes is None:
        codes_set = get_latest_hk_connect_codes()
        if not codes_set:
            logger.warning(
                "hk_industry_updater: 港股通名单为空,跳过(请先跑 hk_connect_updater)"
            )
            return {
                "fetched": 0,
                "skipped": 0,
                "failed": 0,
                "total_rows": 0,
                "path": str(_parquet_path()),
            }
        codes_list = sorted(codes_set)
    else:
        codes_list = sorted(set(codes))

    path = _parquet_path()
    existing: dict[str, dict] = {}
    if path.exists():
        try:
            old_df = pd.read_parquet(path)
            for _, row in old_df.iterrows():
                existing[str(row["code"])] = {
                    "code": str(row["code"]),
                    "name": row.get("name"),
                    "sector": row.get("sector"),
                    "industry": row.get("industry"),
                    "updated_at": row.get("updated_at"),
                }
        except Exception as e:
            logger.warning("hk_industry_updater: 读旧 parquet 失败,忽略: %s", e)

    cutoff = now.timestamp() - max_age_days * 86400
    fetched = 0
    skipped = 0
    failed = 0

    for i, code in enumerate(codes_list, 1):
        old = existing.get(code)
        if old and old.get("updated_at"):
            try:
                ts = datetime.fromisoformat(str(old["updated_at"])).timestamp()
                if ts >= cutoff:
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                pass  # 解析失败 → 重新抓

        rec = fetch(code)
        if rec is None:
            failed += 1
        else:
            rec["updated_at"] = now_iso
            existing[code] = rec
            fetched += 1

        if i % 50 == 0:
            logger.info(
                "hk_industry_updater: 进度 %d/%d (fetched=%d skipped=%d failed=%d)",
                i,
                len(codes_list),
                fetched,
                skipped,
                failed,
            )
        if sleep_sec > 0 and rec is not None:
            time.sleep(sleep_sec)

    # 落盘 — 全量重写(数据量小,~600 行)
    if existing:
        merged = pd.DataFrame(list(existing.values()))
        # 列顺序固定
        merged = merged[["code", "name", "sector", "industry", "updated_at"]]
        merged = merged.sort_values("code").reset_index(drop=True)
        # 重算型: sector/industry 分类会随 yfinance 更新而合法变动; merged 由旧全集
        # 增量更新而来(未抓的 code 原样保留), 仅护结构 + 灾难性骤减。
        check_write_integrity(path, merged, key="code", mode="recompute")
        merged.to_parquet(path, index=False)
        total_rows = len(merged)
    else:
        total_rows = 0

    # 刷新 DuckDB 视图 + stock_index 内存缓存
    try:
        from backend.services.market_data.duckdb_store import get_store

        get_store().refresh_hk_industry_view()
    except Exception as e:
        logger.warning("hk_industry_updater: 刷新 DuckDB 视图失败(忽略): %s", e)
    try:
        from backend.services.market_data.stock_index import refresh_hk_industry

        refresh_hk_industry()
    except Exception as e:
        logger.warning("hk_industry_updater: 刷新 stock_index 失败(忽略): %s", e)

    logger.info(
        "hk_industry_updater: 完成 fetched=%d skipped=%d failed=%d total=%d -> %s",
        fetched,
        skipped,
        failed,
        total_rows,
        path,
    )
    return {
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "total_rows": total_rows,
        "path": str(path),
    }
