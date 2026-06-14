"""§7 控股股东 — 按需拉取 + 7 天 mtime 缓存。

逻辑:
1. parquet 不存在 / mtime 已过 ttl_days → 调 EastMoney adapter 拉取 → append + dedup → 返回最新合集
2. 缓存命中 → 直接读 parquet
3. 远程失败 → 优雅降级:有旧数据返旧数据 + warning;无数据返空

调用方:DuckDBStore.query_top10_holders / query_top10_free_holders / query_holder_count
(每个 query 前先调 fetch_with_cache 刷数据,再读 parquet 给 section)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.repositories.holder_repo import HolderRepository

logger = logging.getLogger(__name__)


class HolderUpdater:
    def __init__(
        self,
        repo: HolderRepository,
        adapter: Optional[EastMoneyAdapter] = None,
        ttl_days: int = 7,
    ):
        self.repo = repo
        self.adapter = adapter or EastMoneyAdapter()
        self.ttl_seconds = ttl_days * 86400

    # ---------- public API ----------
    def fetch_with_cache(self, code: str, table: str):
        """读 (code, table) 数据;mtime 过期/缺失则刷新 + 返回最新合集。"""
        if table not in ("top10", "top10_free", "holder_count"):
            raise ValueError(f"unknown holder table: {table}")

        path = self.repo.parquet_path(code, table)
        fresh = (
            path.exists() and (time.time() - path.stat().st_mtime) < self.ttl_seconds
        )

        if fresh:
            return self._read(code, table)

        # 需要刷新
        try:
            new_records = self._fetch_remote(code, table)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "holder_updater fetch_remote failed (%s, %s): %s — fallback to existing",
                code,
                table,
                e,
            )
            return self._read(code, table)

        if new_records:
            self._append(code, table, new_records)

        return self._read(code, table)

    # ---------- internal ----------
    def _fetch_remote(self, code: str, table: str):
        if table == "top10":
            return self.adapter.fetch_top10_holders(code)
        if table == "top10_free":
            return self.adapter.fetch_top10_free_holders(code)
        if table == "holder_count":
            return self.adapter.fetch_holder_count_history(code)
        raise ValueError(table)

    def _append(self, code: str, table: str, records):
        if table == "top10":
            self.repo.append_top10_holders(code, records)
        elif table == "top10_free":
            self.repo.append_top10_free_holders(code, records)
        elif table == "holder_count":
            self.repo.append_holder_count(code, records)

    def _read(self, code: str, table: str):
        if table == "top10":
            return self.repo.read_top10_holders(code)
        if table == "top10_free":
            return self.repo.read_top10_free_holders(code)
        if table == "holder_count":
            return self.repo.read_holder_count(code)
        return []
