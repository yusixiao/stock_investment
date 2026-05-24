"""Tavily search 客户端 — 7 天文件缓存 + 优雅降级。

设计原则:
- 无 API key → search_with_cache 返回 None,上游降级到「数据待补」文案
- 命中缓存(mtime < ttl_days) → 直接返回 JSON,不打网络
- 网络失败 + 旧缓存存在 → 返回旧缓存 + warning;旧缓存不存在 → 返回 None
- 缓存文件名:`{code}_{section}.json`,section 区分 industry / esg

调用方:s08_industry.build / s10_esg.build,通过 DataPackBuilder.tavily 注入
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("cache") / "tavily"


class TavilyClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        ttl_days: int = 7,
        max_results: int = 5,
    ):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.ttl_seconds = ttl_days * 86400
        self.max_results = max_results
        # 懒构造真实 SDK 客户端(允许单测无 SDK 跑)
        self._sdk = None

    # ---------- public ----------
    def search_with_cache(
        self,
        code: str,
        section: str,
        query: str,
        max_results: Optional[int] = None,
    ) -> Optional[dict]:
        """读 (code, section) 缓存,过期则刷新。无 key 直接返 None。"""
        if not self.api_key:
            return None

        cache_path = self._cache_path(code, section)
        fresh = (
            cache_path.exists()
            and (time.time() - cache_path.stat().st_mtime) < self.ttl_seconds
        )
        if fresh:
            return self._read(cache_path)

        # 需要刷新
        try:
            payload = self._search(query, max_results or self.max_results)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "tavily search failed (%s, %s): %s — fallback to cache",
                code,
                section,
                e,
            )
            if cache_path.exists():
                return self._read(cache_path)
            return None

        if payload is None:
            if cache_path.exists():
                return self._read(cache_path)
            return None

        self._write(cache_path, payload)
        return payload

    # ---------- internal ----------
    def _cache_path(self, code: str, section: str) -> Path:
        safe = code.replace("/", "_")
        return self.cache_dir / f"{safe}_{section}.json"

    @staticmethod
    def _read(path: Path) -> Optional[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("tavily cache read failed (%s): %s", path, e)
            return None

    def _write(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _search(self, query: str, max_results: int) -> Optional[dict]:
        """调真实 Tavily SDK。返回 dict({answer, results, ...})或抛异常。"""
        if self._sdk is None:
            try:
                from tavily import TavilyClient as _SDK
            except Exception as e:  # noqa: BLE001
                logger.warning("tavily-python not installed: %s", e)
                return None
            self._sdk = _SDK(self.api_key)

        return self._sdk.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_answer=True,
        )
