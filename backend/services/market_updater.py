"""
统一增量更新服务 — A/HK/US 三市场 K线 + 复权因子 + 财务数据。

设计原则：
- 不使用 tracker 文件，直接从 parquet 读最新日期作为增量起点
- 复用 adapter 层（BaoStock / yfinance）和 repository 层（去重写入）
- 三市场并行执行，各自独立连接
- 进度/日志持久化到 SQLite
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Optional, Callable

from config import DATA_DIR

logger = logging.getLogger(__name__)


def _get_adapter(market: str):
    """延迟导入 adapter，避免模块级 backend.xxx 前缀冲突"""
    if market == "A":
        from backend.adapters.baostock_adapter import BaoStockAdapter

        return BaoStockAdapter()
    else:
        from backend.adapters.yfinance_adapter import YFinanceAdapter

        return YFinanceAdapter()


def _get_repo(market: str):
    """延迟导入 repository"""
    from backend.repositories.market_repo import MarketRepository

    daily_dir = DATA_DIR / "market" / market / "daily"
    adjust_dir = DATA_DIR / "market" / market / "adjust_factor"
    return MarketRepository(daily_dir, adjust_dir)


MARKETS = ["A", "HK", "US"]

MAX_RETRIES = 3
RETRY_BACKOFF_CAP = 30


@dataclass
class MarketUpdateResult:
    market: str = ""
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)
    elapsed_sec: float = 0.0


@dataclass
class UpdateProgress:
    status: str = "idle"  # idle | running | completed | failed
    started_at: str = ""
    finished_at: str = ""
    current_market: str = ""
    current_index: int = 0
    total_stocks: int = 0
    results: list = field(default_factory=list)


_progress = UpdateProgress()


def get_update_progress() -> dict:
    return asdict(_progress)


def _fetch_with_retry(
    adapter,
    code: str,
    start_date: str,
    end_date: str,
    max_retries: int = MAX_RETRIES,
):
    """带重试的 K线拉取"""
    last_error = None
    for attempt in range(max_retries):
        try:
            return adapter.fetch_daily_kline(code, start_date, end_date)
        except Exception as e:
            last_error = e
            wait = min(2**attempt, RETRY_BACKOFF_CAP)
            logger.warning(
                f"Fetch failed {code} attempt {attempt + 1}/{max_retries}, "
                f"wait {wait}s: {e}"
            )
            time.sleep(wait)
    raise RuntimeError(f"{code} failed after {max_retries} retries: {last_error}")


def _update_market_kline(
    market: str, on_progress: Optional[Callable] = None
) -> MarketUpdateResult:
    """增量更新单个市场的 K线数据"""
    adapter = _get_adapter(market)
    repo = _get_repo(market)

    if hasattr(adapter, "login"):
        adapter.login()

    result = MarketUpdateResult(market=market)
    t0 = time.time()

    codes = repo.list_codes()
    if not codes:
        logger.info(f"[{market}] No existing parquet files, skip")
        return result

    total = len(codes)
    end_date = date.today().strftime("%Y-%m-%d")
    logger.info(
        f"[{market}] Start incremental update: {total} stocks, end_date={end_date}"
    )

    for idx, code in enumerate(codes, 1):
        try:
            latest = repo.get_latest_date(code)

            if latest and latest >= end_date:
                result.skipped += 1
                continue

            start = (
                latest
                if not latest
                else (
                    datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")
            )

            if not latest:
                start = "2010-01-01"

            if start > end_date:
                result.skipped += 1
                continue

            records = _fetch_with_retry(adapter, code, start, end_date)

            if not records:
                result.skipped += 1
                continue

            repo.append_daily_kline(code, records)
            result.updated += 1

        except Exception as e:
            result.failed += 1
            if len(result.errors) < 50:
                result.errors.append(f"{code}: {e}")
            logger.error(f"[{market}] Failed {code}: {e}")

        if on_progress and idx % 100 == 0:
            on_progress(market, idx, total)

    if hasattr(adapter, "logout"):
        adapter.logout()

    result.elapsed_sec = round(time.time() - t0, 2)
    logger.info(
        f"[{market}] Done: updated={result.updated} skipped={result.skipped} "
        f"failed={result.failed} elapsed={result.elapsed_sec}s"
    )
    return result


def _update_market_adjust_factor(market: str) -> int:
    """更新单个市场的复权因子（全量覆盖）"""
    adapter = _get_adapter(market)
    repo = _get_repo(market)

    codes = repo.list_codes()
    updated = 0

    for code in codes:
        try:
            records = adapter.fetch_adjust_factor(code)
            if records:
                repo.write_adjust_factor(code, records)
                updated += 1
        except Exception as e:
            logger.warning(f"[{market}] Adjust factor failed {code}: {e}")

    logger.info(f"[{market}] Adjust factor updated: {updated}/{len(codes)}")
    return updated


def update_all_markets(parallel: bool = True) -> list[MarketUpdateResult]:
    """
    增量更新三市场 K线数据。
    parallel=True 时三市场并行执行。
    """
    global _progress
    _progress = UpdateProgress(
        status="running",
        started_at=datetime.now().isoformat(),
    )

    def _on_progress(market: str, idx: int, total: int):
        _progress.current_market = market
        _progress.current_index = idx
        _progress.total_stocks = total

    results = []

    if parallel:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_update_market_kline, m, _on_progress): m
                for m in MARKETS
            }
            for future in as_completed(futures):
                market = futures[future]
                try:
                    r = future.result()
                    results.append(r)
                except Exception as e:
                    logger.error(f"[{market}] Update thread failed: {e}")
                    results.append(
                        MarketUpdateResult(market=market, failed=-1, errors=[str(e)])
                    )
    else:
        for market in MARKETS:
            r = _update_market_kline(market, _on_progress)
            results.append(r)

    _progress.status = "completed"
    _progress.finished_at = datetime.now().isoformat()
    _progress.results = [asdict(r) for r in results]

    total_updated = sum(r.updated for r in results)
    total_failed = sum(r.failed for r in results)
    logger.info(
        f"All markets done: total_updated={total_updated} total_failed={total_failed}"
    )

    return results


def update_single_market(market: str) -> MarketUpdateResult:
    """增量更新单个市场"""
    if market not in MARKETS:
        raise ValueError(f"Unknown market: {market}, expected one of {MARKETS}")
    return _update_market_kline(market)


def update_adjust_factors(markets: Optional[list[str]] = None) -> dict:
    """更新复权因子（默认全部市场）"""
    markets = markets or list(MARKETS)
    results = {}
    for m in markets:
        results[m] = _update_market_adjust_factor(m)
    return results
