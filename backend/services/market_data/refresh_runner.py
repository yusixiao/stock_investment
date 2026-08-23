"""统一编排市场更新、view 刷新和 data_cache 重建。"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from config import PORTFOLIO_DB
from services.market_data.refresh_state import RefreshStateStore

logger = logging.getLogger(__name__)
MARKETS = ("A", "HK", "US")


def _default_update_market(market: str):
    from services.market_data.updaters.market_updater import update_single_market

    return update_single_market(market)


def _default_refresh_view(_market: str) -> dict[str, Any]:
    from services.market_data.duckdb_store import reload_views

    reload_views()
    return {"status": "success"}


def _default_refresh_cache(market: str, refresh_id: str | None = None) -> dict[str, Any]:
    from services.backtest import data_cache

    data_cache.invalidate(market)
    generation = data_cache.get_generation(market)
    data_cache.load_market_async(market, generation=generation, refresh_id=refresh_id)
    deadline = time.monotonic() + 7200
    while time.monotonic() < deadline:
        status = data_cache.get_status(market)
        if status["status"] == "loaded":
            return {"status": "ready", "stale": False}
        if status["status"] == "failed":
            return {"status": "failed", "stale": True, "error": status.get("error")}
        time.sleep(1)
    data_cache.invalidate(market)
    return {"status": "failed", "stale": True, "error": "cache rebuild timeout"}


def _default_set_market_metadata(
    market: str, refresh_id: str | None, market_version: int | None, stale: bool
) -> None:
    from services.backtest import data_cache

    data_cache.set_market_metadata(market, refresh_id, market_version, stale)


def _result_detail(result: Any) -> dict[str, Any]:
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {"result": str(result)}


class RefreshRunner:
    """一个 refresh 只允许一个实例运行，市场内部仍可并行更新。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        update_market: Callable[[str], Any] = _default_update_market,
        update_markets: Callable[[], list[Any]] | None = None,
        refresh_view: Callable[[str], dict[str, Any]] = _default_refresh_view,
        refresh_views: Callable[[list[str]], dict[str, Any]] | None = None,
        refresh_cache: Callable[[str, str | None], dict[str, Any]] = _default_refresh_cache,
        refresh_before_cache: Callable[[list[str]], Any] | None = None,
        set_market_metadata: Callable[[str, str | None, int | None, bool], None]
        = _default_set_market_metadata,
        auto_start: bool = True,
        on_complete: Callable[[Any], None] | None = None,
    ):
        self.store = RefreshStateStore(db_path or PORTFOLIO_DB)
        self.update_market = update_market
        self.update_markets = update_markets
        self.refresh_view = refresh_view
        self.refresh_views = refresh_views
        self.refresh_cache = refresh_cache
        self.refresh_before_cache = refresh_before_cache
        self.set_market_metadata = set_market_metadata
        self.auto_start = auto_start
        self.on_complete = on_complete

    def start(self, source: str, markets: list[str] | None = None):
        selected = [m.upper() for m in (markets or MARKETS)]
        invalid = set(selected) - set(MARKETS)
        if invalid:
            raise ValueError(f"Unknown markets: {sorted(invalid)}")
        record = self.store.start_refresh(source)
        if self.auto_start:
            threading.Thread(
                target=self._run_background,
                args=(record.refresh_id, selected),
                daemon=True,
                name=f"market_refresh_{record.refresh_id}",
            ).start()
        return record

    def _run_background(self, refresh_id: str, markets: list[str]) -> None:
        self.run(refresh_id, markets)

    def run(self, refresh_id: str, markets: list[str]) -> None:
        failures: dict[str, str] = {}
        successes: set[str] = set()

        if self.update_markets:
            self._update_many(refresh_id, markets, successes, failures)
        else:
            with ThreadPoolExecutor(max_workers=len(markets)) as executor:
                futures = {
                    executor.submit(self._update_one, refresh_id, market): market
                    for market in markets
                }
                for future in as_completed(futures):
                    market = futures[future]
                    try:
                        if future.result():
                            successes.add(market)
                        else:
                            failures[market] = "market update failed"
                    except Exception as exc:  # noqa: BLE001
                        failures[market] = str(exc)

        for market in failures:
            self._record_stale(refresh_id, market, failures[market])

        if self.refresh_before_cache and successes:
            try:
                precache_successes = self.refresh_before_cache(sorted(successes))
                if precache_successes is not None:
                    precache_successes = set(precache_successes)
                    precache_failures = successes - precache_successes
                    for market in precache_failures:
                        failures[market] = "pre-cache failed"
                        self._record_stale(refresh_id, market, failures[market])
                    successes.intersection_update(precache_successes)
            except Exception as exc:  # noqa: BLE001
                for market in successes:
                    failures[market] = f"pre-cache: {exc}"
                    self._record_stale(refresh_id, market, str(exc))
                successes.clear()

        view_ready_markets = self._refresh_views(refresh_id, sorted(successes), failures)
        for market in view_ready_markets:
            self._refresh_derived(refresh_id, market, failures)

        status = "completed" if not failures else "partial"
        error = json.dumps(failures, ensure_ascii=False) if failures else None
        self.store.finish_refresh(refresh_id, status, error)
        if self.on_complete:
            self.on_complete(self.store.get(refresh_id))

    def _update_many(
        self,
        refresh_id: str,
        markets: list[str],
        successes: set[str],
        failures: dict[str, str],
    ) -> None:
        update_markets = self.update_markets
        if update_markets is None:
            return
        for market in markets:
            self.store.record_market_stage(refresh_id, market, "update", "running")
        try:
            results = {
                result.market: result
                for result in update_markets()
            }
        except Exception as exc:  # noqa: BLE001
            for market in markets:
                failures[market] = str(exc)
                self.store.record_market_stage(
                    refresh_id,
                    market,
                    "update",
                    "failed",
                    {"error": str(exc), "aborted": True},
                )
            return
        for market in markets:
            result = results.get(market)
            if result is None:
                failures[market] = "market update returned no result"
                self.store.record_market_stage(
                    refresh_id, market, "update", "failed", {}
                )
                continue
            detail = _result_detail(result)
            failed = int(detail.get("failed", 0)) > 0 or bool(detail.get("aborted"))
            self.store.record_market_stage(
                refresh_id,
                market,
                "update",
                "failed" if failed else "success",
                detail,
            )
            if failed:
                failures[market] = "market update failed"
            else:
                successes.add(market)

    def _update_one(self, refresh_id: str, market: str) -> bool:
        self.store.record_market_stage(refresh_id, market, "update", "running")
        try:
            result = self.update_market(market)
            detail = _result_detail(result)
            failed = int(detail.get("failed", 0)) > 0 or bool(detail.get("aborted"))
            self.store.record_market_stage(
                refresh_id,
                market,
                "update",
                "failed" if failed else "success",
                detail,
            )
            return not failed
        except Exception as exc:  # noqa: BLE001
            self.store.record_market_stage(
                refresh_id,
                market,
                "update",
                "failed",
                {"error": str(exc), "aborted": True},
            )
            return False

    def _refresh_views(
        self, refresh_id: str, markets: list[str], failures: dict[str, str]
    ) -> list[str]:
        if not markets:
            return []
        for market in markets:
            self.store.record_market_stage(refresh_id, market, "view", "running")
        try:
            # DuckDB views are global; the legacy adapter receives the first
            # market only for compatibility, while the new adapter sees the
            # complete successful market set once.
            view_detail = (
                self.refresh_views(markets)
                if self.refresh_views is not None
                else self.refresh_view(markets[0])
            )
        except Exception as exc:  # noqa: BLE001
            for market in markets:
                failures[market] = f"view: {exc}"
                self.store.record_market_stage(
                    refresh_id, market, "view", "failed", {"error": str(exc)}
                )
                self._record_stale(refresh_id, market, str(exc))
            return []

        for market in markets:
            self.store.record_market_stage(
                refresh_id, market, "view", "success", view_detail
            )
        return markets

    def _refresh_derived(
        self, refresh_id: str, market: str, failures: dict[str, str]
    ) -> None:

        self.store.record_market_stage(refresh_id, market, "cache", "running")
        try:
            cache_detail = self.refresh_cache(market, refresh_id)
            cache_status = cache_detail.get("status", "failed")
            if cache_status != "ready":
                failures[market] = f"cache: {cache_detail.get('error', cache_status)}"
                self.store.record_market_stage(
                    refresh_id, market, "cache", cache_status, cache_detail
                )
                self._record_stale(refresh_id, market, cache_detail.get("error"))
                return
            version = self.store.advance_market_version(market)
            self.store.record_market_stage(
                refresh_id,
                market,
                "cache",
                "success",
                {**cache_detail, "market_version": version},
            )
            self.store.finish_market(refresh_id, market, version, "ready", False)
            self._set_market_metadata_best_effort(market, refresh_id, version, False)
        except Exception as exc:  # noqa: BLE001
            failures[market] = f"cache: {exc}"
            self.store.record_market_stage(
                refresh_id, market, "cache", "failed", {"error": str(exc)}
            )
            self._record_stale(refresh_id, market, str(exc))

    def _record_stale(self, refresh_id: str, market: str, error: Any) -> None:
        version = self.store.get_market_version(market)

        self.store.finish_market(refresh_id, market, version, "stale", True)
        self._set_market_metadata_best_effort(market, refresh_id, version, True)

    def _set_market_metadata_best_effort(
        self, market: str, refresh_id: str, version: int, stale: bool
    ) -> None:
        try:
            self.set_market_metadata(market, refresh_id, version, stale)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write cache metadata for market %s", market)
