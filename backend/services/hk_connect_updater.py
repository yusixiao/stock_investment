"""港股通成分股 updater — 拉 EastMoney push2 接口,落 parquet 单文件 append。

数据落点(AGENTS.md 铁律 — 业务数据必须落 data/market/):
  data/market/HK/membership/hk_connect.parquet

schema:
  as_of_date  str  YYYY-MM-DD,该次快照日期(本地日期)
  code        str  5 位 HK 代码(带前导 0,如 "09988")
  name        str  港股名称
  board       str  EastMoney 板块代码(默认 DLMK0146)

去重键:(as_of_date, code, board) — 同一天同板块只保留一份
排序:as_of_date desc, code asc

⚠️ push2 接口仅返回当前快照,无历史进出名单。回测如需严格 point-in-time
判断"某股 X 日是否港股通成分股",此数据源不足(详见 AGENTS.md "港股通"段)。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.config import MARKET_DIR

logger = logging.getLogger(__name__)


def _parquet_path() -> Path:
    """港股通快照 parquet 路径。"""
    p = MARKET_DIR / "HK" / "membership" / "hk_connect.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def fetch_and_save_hk_connect(
    board_code: str = "DLMK0146",
    as_of: str | None = None,
) -> dict:
    """拉取港股通成分股快照 + append 到 parquet。

    Args:
        board_code: 板块代码(DLMK0146=全集 / DLMK0144=沪 / DLMK0145=深独有)
        as_of: 快照日期(YYYY-MM-DD),None 则用今天

    Returns:
        {"count": int, "as_of_date": str, "board": str, "path": str}
        若拉取失败 count=0。
    """
    as_of_date = as_of or date.today().strftime("%Y-%m-%d")

    adapter = EastMoneyAdapter()
    members = adapter.fetch_hk_connect_members(board_code=board_code)
    if not members:
        # push2 限流时降级到 datacenter-web RPT_MUTUAL_STOCK_HOLDRANKS
        logger.warning(
            "hk_connect_updater: push2 拉取空结果,降级到 datacenter-web holdrank"
        )
        members = adapter.fetch_hk_connect_members_holdrank()
    if not members:
        logger.warning(
            "hk_connect_updater: 全部数据源失败 board=%s as_of=%s",
            board_code,
            as_of_date,
        )
        return {
            "count": 0,
            "as_of_date": as_of_date,
            "board": board_code,
            "path": str(_parquet_path()),
        }

    # 转 DataFrame 标准 schema
    new_df = pd.DataFrame(
        [
            {
                "as_of_date": as_of_date,
                "code": m["code"],
                "name": m["name"],
                "board": board_code,
            }
            for m in members
        ]
    )

    path = _parquet_path()
    if path.exists():
        try:
            old_df = pd.read_parquet(path)
            merged = pd.concat([old_df, new_df], ignore_index=True)
            # 去重:同一天同板块同 code 只留最后写入(新数据覆盖旧)
            merged = merged.drop_duplicates(
                subset=("as_of_date", "code", "board"), keep="last"
            )
        except Exception as e:
            logger.warning(
                "hk_connect_updater: 读取已有 parquet 失败,改为覆盖写: %s", e
            )
            merged = new_df
    else:
        merged = new_df

    # 排序:as_of_date desc, code asc(便于查询最新快照)
    merged = merged.sort_values(
        ["as_of_date", "code"], ascending=[False, True]
    ).reset_index(drop=True)
    merged.to_parquet(path, index=False)
    invalidate_cache()

    # DuckDB 视图(v_hk_connect_latest + v_hk_periodic_report)依赖 parquet,
    # parquet 从无到有时 init 已 skip,这里主动 refresh 让本进程立即可用
    try:
        from backend.services.duckdb_store import get_store

        get_store().refresh_hk_connect_view()
    except Exception as e:
        logger.warning("hk_connect_updater: 刷新 DuckDB 视图失败(忽略): %s", e)

    logger.info(
        "hk_connect_updater: 写入 %d 行 (本次新增 %d / 累计 %d) board=%s as_of=%s -> %s",
        len(new_df),
        len(merged) - (len(old_df) if path.exists() and "old_df" in locals() else 0),
        len(merged),
        board_code,
        as_of_date,
        path,
    )

    return {
        "count": len(new_df),
        "total_rows": len(merged),
        "as_of_date": as_of_date,
        "board": board_code,
        "path": str(path),
    }


_codes_cache: dict[str | None, set[str]] = {}


def invalidate_cache() -> None:
    """清空 get_latest_hk_connect_codes 内存缓存(写入新快照后调用)。"""
    _codes_cache.clear()


def get_latest_hk_connect_codes(board_code: str | None = None) -> set[str]:
    """读最新快照的 HK 代码集合(供 ScreenContext 等使用)。

    Args:
        board_code: 限定板块,None 则不限(取所有板块的最新日期 union)

    Returns:
        set of code(5 位 HK 带前导 0,如 "09988")
        无数据返空集。
    """
    if board_code in _codes_cache:
        return _codes_cache[board_code]

    path = _parquet_path()
    if not path.exists():
        _codes_cache[board_code] = set()
        return set()
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        logger.warning("get_latest_hk_connect_codes: 读 parquet 失败: %s", e)
        return set()
    if len(df) == 0:
        _codes_cache[board_code] = set()
        return set()
    if board_code:
        df = df[df["board"] == board_code]
        if len(df) == 0:
            _codes_cache[board_code] = set()
            return set()
    latest = df["as_of_date"].max()
    codes = set(df[df["as_of_date"] == latest]["code"].astype(str).tolist())
    _codes_cache[board_code] = codes
    return codes
