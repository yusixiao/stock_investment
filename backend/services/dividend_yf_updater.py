"""HK/US 分红数据增量更新 — yfinance Ticker.dividends 事件级每股分红。

设计:
- 数据源: yfinance(Ticker.dividends 返回事件级每股分红 Series,与 A 股 schema 对齐)
- 落地:   data/market/{HK,US}/dividend/{code}.parquet,英文 schema(BaoStock 原生 DividendRecord)
- 范式参照 services/dividend_market_updater.py(A 股 EastMoney 版)

为什么不复用 cashflow.DIVIDENDS_PAID 派生:
- HK 缺流通股字段(只有 SHARE_CAPITAL 面值/TREASURY_SHARES 库存股),无法算每股
- US 虽有 COMMON_STOCK_SHARES 但粒度仅到年报,无法识别一年多次分红事件
- yfinance 直接提供 ex-dividend date + 每股金额,字段对齐 A 股(dividOperateDate / dividCashPsBeforeTax)

并发:
- yfinance 支持适度并发,但 Yahoo 限流明显;默认 max_workers=4
- 单股 1 次调用 ≈ 0.5-2s,HK 2733 + US 6497 ≈ 1-2 小时
"""

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)


@dataclass
class DividendUpdateResult:
    market: str = ""
    updated: int = 0
    skipped: int = 0  # 无分红记录
    failed: int = 0
    errors: list = field(default_factory=list)
    elapsed_sec: float = 0.0


@dataclass
class DividendUpdateProgress:
    status: str = "idle"  # idle | running | completed | failed
    market: str = ""
    started_at: str = ""
    finished_at: str = ""
    current_index: int = 0
    total_stocks: int = 0
    current_code: str = ""
    result: dict = field(default_factory=dict)


_progress = DividendUpdateProgress()


def get_progress() -> dict:
    return asdict(_progress)


def _get_adapter():
    from backend.adapters.yfinance_adapter import YFinanceAdapter

    return YFinanceAdapter()


def _get_repo(market: str):
    from backend.repositories.event_repo import EventRepository

    return EventRepository(DATA_DIR / "market" / market)


def _list_codes(market: str) -> list[str]:
    """从 data/market/{market}/daily/ 列出所有股票代码。"""
    daily_dir = DATA_DIR / "market" / market / "daily"
    if not daily_dir.exists():
        return []
    return sorted(p.stem for p in daily_dir.glob("*.parquet"))


def update_dividend(
    market: str,
    codes: Optional[list[str]] = None,
    incremental: bool = True,
    max_workers: int = 2,
    skip_existing: bool = True,
) -> DividendUpdateResult:
    """HK/US 分红事件抓取(yfinance)。

    参数:
        market: "HK" | "US"
        codes: None 时使用 daily 目录下所有股票
        incremental: True 时,合并已有 parquet(按 dividOperateDate 去重,新覆盖旧)
        max_workers: 并发线程数,默认 2(Yahoo 限流敏感,实测 4 会快速触发 429)
        skip_existing: True 时,跳过已存在的 parquet(用于断点续抓);
                       置 False 强制全部重抓(覆盖更新)
    """
    global _progress

    if market not in ("HK", "US"):
        raise ValueError(f"unsupported market: {market} (only HK/US)")

    if codes is None:
        codes = _list_codes(market)

    if not codes:
        logger.warning(f"[{market} dividend] no codes to update")
        return DividendUpdateResult(market=market)

    div_dir = DATA_DIR / "market" / market / "dividend"
    div_dir.mkdir(parents=True, exist_ok=True)

    if skip_existing:
        existed = {p.stem for p in div_dir.glob("*.parquet")}
        before = len(codes)
        codes = [c for c in codes if c not in existed]
        logger.info(
            f"[{market} dividend] skip_existing=True: {before} → {len(codes)} "
            f"(已抓 {before - len(codes)} 只)"
        )

    _progress = DividendUpdateProgress(
        status="running",
        market=market,
        started_at=datetime.now().isoformat(),
        total_stocks=len(codes),
    )

    result = DividendUpdateResult(market=market)
    t0 = time.time()
    repo = _get_repo(market)
    adapter = _get_adapter()

    total = len(codes)
    log_every = 100

    # 完成计数器(并发场景需保护)
    done = {"count": 0}
    import threading

    lock = threading.Lock()

    def _worker(code: str):
        try:
            _process_one(adapter, repo, code, incremental, result, lock)
        except Exception as e:
            with lock:
                result.failed += 1
                if len(result.errors) < 50:
                    result.errors.append(f"{code}: {e}")
            logger.error(f"[{market} dividend] worker failed {code}: {e}")
        finally:
            with lock:
                done["count"] += 1
                idx = done["count"]
                _progress.current_index = idx
                _progress.current_code = code
                if idx % log_every == 0 or idx == total:
                    el = time.time() - t0
                    rate = idx / el if el > 0 else 0
                    eta_h = (total - idx) / rate / 3600 if rate > 0 else 0
                    logger.info(
                        f"[{market} dividend] progress {idx}/{total} "
                        f"updated={result.updated} skipped={result.skipped} "
                        f"failed={result.failed} rate={rate:.2f}/s eta={eta_h:.1f}h"
                    )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, c) for c in codes]
        for _ in as_completed(futures):
            pass

    result.elapsed_sec = round(time.time() - t0, 2)
    _progress.status = "completed"
    _progress.finished_at = datetime.now().isoformat()
    _progress.result = asdict(result)

    logger.info(
        f"[{market} dividend] Done: updated={result.updated} skipped={result.skipped} "
        f"failed={result.failed} elapsed={result.elapsed_sec}s"
    )
    return result


def _is_rate_limited(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "too many requests" in msg or "rate limit" in msg or "429" in msg


def _fetch_with_retry(adapter, code: str, max_attempts: int = 4):
    """对 yfinance 限流(429)做指数退避重试,其它异常直接抛出。"""
    for attempt in range(max_attempts):
        try:
            return adapter.fetch_dividends(code)
        except Exception as e:
            if _is_rate_limited(e) and attempt < max_attempts - 1:
                # 指数退避 + 抖动:5s, 10s, 20s
                sleep = 5 * (2**attempt) + random.uniform(0, 2)
                logger.warning(
                    f"[dividend] {code} rate-limited, sleep {sleep:.1f}s "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )
                time.sleep(sleep)
                continue
            raise
    raise RuntimeError(f"{code}: rate-limited after {max_attempts} attempts")


def _process_one(adapter, repo, code: str, incremental: bool, result, lock) -> None:
    """单股处理:抓取 → 合并 → 落盘。"""
    new_records = _fetch_with_retry(adapter, code)

    if not new_records:
        with lock:
            result.skipped += 1
        return

    if incremental:
        try:
            existing = repo.read_dividends(code)
        except FileNotFoundError:
            existing = []
        merged_map = {r.dividOperateDate: r for r in existing}
        for r in new_records:
            merged_map[r.dividOperateDate] = r
        final_records = list(merged_map.values())
    else:
        final_records = new_records

    repo.write_dividends(code, final_records)
    with lock:
        result.updated += 1
