"""A 股 ST 状态查询(通用能力,跨策略复用)。

从 v_a_daily 拉所有 isST=='1' 的 (symbol, date) 对,聚成稀疏 lookup,
供各策略按"当日是否 ST"剔除标的。A 股专用(港股/美股无 ST 机制)。

进程级单例 + 线程锁缓存:全市场 ST 历史记录稀疏(约 1% 行),
预计百万级 (sym, date) 对,几十 MB,首个回测构建一次后全程复用。
"""

from __future__ import annotations

import threading

_ST_LOOKUP: dict[str, set[str]] | None = None
_ST_LOCK = threading.Lock()


def _build_st_lookup() -> dict[str, set[str]]:
    """从 v_a_daily 拉所有 isST='1' 的 (sym, date),按 sym 聚成 set。

    A 股全市场 ST 历史记录稀疏(约 1% 行),预计百万级,几十 MB。
    """
    from services.market_data.duckdb_store import get_store

    store = get_store()
    sql = """
        SELECT _symbol AS code, date
        FROM v_a_daily
        WHERE isST = '1'
    """
    df = store._conn.execute(sql).fetchdf()
    df["date"] = df["date"].astype(str)
    out: dict[str, set[str]] = {}
    for code, sub in df.groupby("code"):
        out[code] = set(sub["date"].tolist())
    return out


def _get_st_lookup() -> dict[str, set[str]]:
    global _ST_LOOKUP
    if _ST_LOOKUP is not None:
        return _ST_LOOKUP
    with _ST_LOCK:
        if _ST_LOOKUP is None:
            _ST_LOOKUP = _build_st_lookup()
    return _ST_LOOKUP


def reset_st_cache() -> None:
    """测试 / 数据更新后重置 cache。"""
    global _ST_LOOKUP
    with _ST_LOCK:
        _ST_LOOKUP = None


def _is_st_on(symbol: str, date_str: str) -> bool:
    return date_str in _get_st_lookup().get(symbol, set())
