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
from datetime import date, datetime, time as dtime, timedelta
from typing import Optional, Callable

from zoneinfo import ZoneInfo

from config import DATA_DIR
from services.market_data.hk_price_cleaner import clean_transient_scale_spikes

logger = logging.getLogger(__name__)


# 各市场收盘时间(本地时区)。增量更新只取至「最近一个已收盘的交易日」,
# 避免把盘中 partial bar 写入历史。
_MARKET_CLOSE = {
    "A": (ZoneInfo("Asia/Shanghai"), dtime(15, 0)),
    "HK": (ZoneInfo("Asia/Hong_Kong"), dtime(16, 10)),  # +10min 缓冲数据落库
    "US": (ZoneInfo("America/New_York"), dtime(16, 10)),
}


def _last_closed_trading_date(market: str) -> str:
    """返回该市场「最后一个已收盘」的日期(YYYY-MM-DD)。
    若当前时间已过当地收盘 → 用当地今日;否则用昨日。
    周末不专门跳过,因 yfinance/BaoStock 对非交易日返回空,append 时无影响。
    """
    tz, close_t = _MARKET_CLOSE.get(market, (ZoneInfo("UTC"), dtime(23, 59)))
    now_local = datetime.now(tz)
    if now_local.time() >= close_t:
        d = now_local.date()
    else:
        d = now_local.date() - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _get_adapter(market: str):
    """延迟导入 adapter，避免模块级 backend.xxx 前缀冲突"""
    if market == "A":
        from backend.adapters.baostock_adapter import BaoStockAdapter

        return BaoStockAdapter()
    elif market == "HK":
        from backend.adapters.eastmoney_adapter import EastMoneyAdapter

        return EastMoneyAdapter()
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

# 熔断阈值:单市场增量中「连续失败」达到此数即判定数据源会话/服务端异常
# (典型如 baostock 10002007 坏 session 之后后续全挂),立即中止本市场增量,
# 避免在坏会话上硬跑完全市场空转数小时。任意一次成功(含成功但返回空)会把
# 连续计数清零,故间歇性/零星失败不会误触发。中止后交由调度层限次延迟重跑。
CONSECUTIVE_FAILURE_LIMIT = 20

# 单股拉取间节流(秒),用于缓解外部行情接口限流。
# A 股走 BaoStock 不需要节流。
THROTTLE_SEC_BY_MARKET = {
    "A": 0.0,
    "HK": 0.1,
    "US": 0.1,
}


def _is_rate_limit_error(err: Exception) -> bool:
    """识别行情接口 / 通用网络层的限流错误,用于针对性长退避"""
    msg = str(err).lower()
    return (
        "too many requests" in msg
        or "rate limit" in msg
        or "rate-limit" in msg
        or "429" in msg
    )


@dataclass
class MarketUpdateResult:
    market: str = ""
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)
    elapsed_sec: float = 0.0
    aborted: bool = False  # 连续失败触发熔断早停时置 True(未跑完全市场)


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


def _retry_call(fn: Callable, label: str, max_retries: int = MAX_RETRIES):
    """带重试的网络调用通用封装(K线 / 复权因子共用)。

    限流错误使用更长的退避(基础 10s × 指数);其它错误用普通指数退避。
    fn 为无参可调用(实参用 lambda 绑定),label 仅用于日志定位。
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                wait = min(10 * (2**attempt), RETRY_BACKOFF_CAP)
            else:
                wait = min(2**attempt, RETRY_BACKOFF_CAP)
            logger.warning(
                f"Fetch failed {label} attempt {attempt + 1}/{max_retries}, "
                f"wait {wait}s: {e}"
            )
            time.sleep(wait)
    raise RuntimeError(f"{label} failed after {max_retries} retries: {last_error}")


def _fetch_with_retry(
    adapter,
    code: str,
    start_date: str,
    end_date: str,
    max_retries: int = MAX_RETRIES,
):
    """带重试的 K线拉取(委托 _retry_call,行为不变)。"""
    return _retry_call(
        lambda: adapter.fetch_daily_kline(code, start_date, end_date),
        code,
        max_retries,
    )


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
    # 关键: 只更新到「最后一个已收盘交易日」,避免把盘中 partial bar 写入历史
    end_date = _last_closed_trading_date(market)
    throttle_sec = THROTTLE_SEC_BY_MARKET.get(market, 0.0)
    logger.info(
        f"[{market}] Start incremental update: {total} stocks, "
        f"end_date={end_date} (last closed), throttle={throttle_sec}s"
    )

    consecutive_failures = 0  # 熔断计数:任一成功(含成功但空)清零
    for idx, code in enumerate(codes, 1):
        try:
            latest = repo.get_latest_date(code)

            if latest and latest >= end_date:
                result.skipped += 1
                continue

            if not latest:
                start = "2010-01-01"
            elif market == "HK":
                # 保留上一根日线作为清洗窗口左邻居,并由 repository 去重覆盖。
                start = latest
            else:
                start = (
                    datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")

            if start > end_date:
                result.skipped += 1
                continue

            records = _fetch_with_retry(adapter, code, start, end_date)
            if market == "HK":
                records = clean_transient_scale_spikes(records)
            # fetch 成功(即使返回空)即证明数据源会话健康 → 重置熔断计数
            consecutive_failures = 0

            if not records:
                # 真正空数据(delisted / 区间无交易): 计为 skipped
                result.skipped += 1
                continue

            repo.append_daily_kline(code, records)
            result.updated += 1

        except Exception as e:
            # 重试后仍失败(含限流耗尽): 计为 failed,不再混入 skipped
            result.failed += 1
            consecutive_failures += 1
            if len(result.errors) < 50:
                result.errors.append(f"{code}: {e}")
            logger.error(f"[{market}] Failed {code}: {e}")

            # 熔断:连续失败达阈值 → 判定会话/服务端故障,中止本市场,不再空转
            if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                result.aborted = True
                logger.error(
                    f"[{market}] Circuit breaker tripped: {consecutive_failures} "
                    f"consecutive failures, aborting remaining {total - idx} stocks "
                    f"(likely data-source outage; will be retried later)"
                )
                break

        if throttle_sec > 0:
            time.sleep(throttle_sec)

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
    """全量覆盖更新单个市场的复权因子。

    复用 K线更新同款基建:单 session 复用 + 限流重试 + 节流 + 进度日志。
    - baostock(A):若不在此登录,fetch_adjust_factor 会对每只股票各自
      login/logout(数千次),既慢又易被封;此处统一登录复用一个 session。
    - Eastmoney(HK) / yfinance(US):数千只全量极易触发限流,故逐只 throttle + 重试。
    """
    adapter = _get_adapter(market)
    repo = _get_repo(market)

    if hasattr(adapter, "login"):
        adapter.login()

    codes = repo.list_codes()
    total = len(codes)
    throttle_sec = THROTTLE_SEC_BY_MARKET.get(market, 0.0)
    logger.info(
        f"[{market}] Adjust factor full update start: {total} codes, "
        f"throttle={throttle_sec}s"
    )

    updated = 0
    failed = 0
    t0 = time.time()

    for idx, code in enumerate(codes, 1):
        try:
            records = _retry_call(
                lambda c=code: adapter.fetch_adjust_factor(c), code
            )
            if records:
                repo.write_adjust_factor(code, records)
                updated += 1
        except Exception as e:
            # 重试耗尽(含限流)仍失败:计 failed,不阻塞后续个股
            failed += 1
            logger.warning(f"[{market}] Adjust factor failed {code}: {e}")

        if throttle_sec > 0:
            time.sleep(throttle_sec)

        if idx % 200 == 0:
            elapsed = time.time() - t0
            speed = idx / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"[{market}] Adjust factor progress {idx}/{total} "
                f"updated={updated} failed={failed} | {speed:.0f}/h"
            )

    if hasattr(adapter, "logout"):
        adapter.logout()

    logger.info(
        f"[{market}] Adjust factor done: updated={updated} failed={failed} "
        f"total={total} elapsed={time.time() - t0:.0f}s"
    )
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
    aborted = [r.market for r in results if r.aborted]
    logger.info(
        f"All markets done: total_updated={total_updated} "
        f"total_failed={total_failed} aborted={aborted or 'none'}"
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
