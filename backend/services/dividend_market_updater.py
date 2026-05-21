"""A 股分红数据增量更新 — 写到 data/market/A/dividend/。

设计:
- 数据源: BaoStock query_dividend_data(逐年逐股票,API 限制)
- 落地:   data/market/A/dividend/{code}.parquet,英文 schema(BaoStock 原生 DividendRecord)
- 范式参照 services/market_updater.py
- HK/US 不在此模块,从 financial.cashflow.DIVIDENDS_PAID 在 DuckDB 视图侧派生

增量策略:
- 每只股票若已有 parquet,只补抓 [last_year, current_year] 区间;
  若无 parquet,从 year_start(默认 1991,A 股最早分红年份)逐年扫到 current_year
- 全量历史首次跑完后,日常调度只补当前年和前一年(覆盖披露窗口)
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)


DIVIDEND_DIR_NEW = DATA_DIR / "market" / "A" / "dividend"
DEFAULT_YEAR_START = 1991  # A 股最早分红年份


@dataclass
class DividendUpdateResult:
    market: str = "A"
    updated: int = 0  # 实际写入新数据的股票数
    skipped: int = 0  # 已是最新或无分红
    failed: int = 0
    errors: list = field(default_factory=list)
    elapsed_sec: float = 0.0


@dataclass
class DividendUpdateProgress:
    status: str = "idle"  # idle | running | completed | failed
    started_at: str = ""
    finished_at: str = ""
    current_index: int = 0
    total_stocks: int = 0
    current_code: str = ""
    result: dict = field(default_factory=dict)


_progress = DividendUpdateProgress()


def get_dividend_progress() -> dict:
    return asdict(_progress)


def _get_adapter():
    from backend.adapters.baostock_adapter import BaoStockAdapter

    return BaoStockAdapter()


def _get_repo():
    """EventRepository 期待 event_dir,内部拼 dividend/。
    这里直接传 data/market/A,落到 data/market/A/dividend/。
    """
    from backend.repositories.event_repo import EventRepository

    return EventRepository(DATA_DIR / "market" / "A")


def _latest_dividend_year(repo, code: str) -> Optional[int]:
    """读已有 parquet 的最新 dividOperateDate,返回年份(int)。无则 None。"""
    try:
        records = repo.read_dividends(code)
    except FileNotFoundError:
        return None
    if not records:
        return None
    # read_dividends 已按 dividOperateDate desc 排序 → 第一条最新
    op = records[0].dividOperateDate
    if not op or len(op) < 4:
        return None
    try:
        return int(op[:4])
    except ValueError:
        return None


def _fetch_dividend_years(adapter, code: str, year_start: int, year_end: int) -> list:
    """遍历 [year_start, year_end] 年份,合并所有 DividendRecord。

    BaoStock query_dividend_data 按年查询,空年份返回 [],不抛错。
    """
    all_records = []
    for year in range(year_start, year_end + 1):
        try:
            records = adapter.fetch_dividends(code, year=str(year))
            if records:
                all_records.extend(records)
        except Exception as e:
            # 单年失败不阻断,记录到上层 errors
            logger.warning(f"[A] dividend {code} year={year}: {e}")
            raise
    return all_records


def update_a_dividend(
    codes: Optional[list[str]] = None,
    year_start: int = DEFAULT_YEAR_START,
    year_end: Optional[int] = None,
    incremental: bool = True,
    max_workers: int = 1,
) -> DividendUpdateResult:
    """A 股 dividend 全量/增量抓取。

    参数:
        codes: None 时使用 data/market/A/daily/ 下所有股票
        year_start: 首次抓取起始年(默认 1991)
        year_end: 抓取到该年止(默认当前年)
        incremental: True 时,已有 parquet 的股票只补抓 [latest_year, year_end]
                     latest_year 从 parquet 中已有记录推导
        max_workers: 并发线程数(BaoStock 同账号限制,建议 1-3;>3 可能限流)
    """
    global _progress

    if year_end is None:
        year_end = datetime.now().year

    # 默认 codes 来自 daily 目录
    if codes is None:
        from backend.repositories.market_repo import MarketRepository

        repo_market = MarketRepository(
            DATA_DIR / "market" / "A" / "daily",
            DATA_DIR / "market" / "A" / "adjust_factor",
        )
        codes = sorted(repo_market.list_codes())

    DIVIDEND_DIR_NEW.mkdir(parents=True, exist_ok=True)

    _progress = DividendUpdateProgress(
        status="running",
        started_at=datetime.now().isoformat(),
        total_stocks=len(codes),
    )

    result = DividendUpdateResult()
    t0 = time.time()
    repo = _get_repo()
    adapter = _get_adapter()
    adapter.login()

    try:
        if max_workers <= 1:
            for idx, code in enumerate(codes, 1):
                _progress.current_index = idx
                _progress.current_code = code
                _process_one(
                    adapter, repo, code, year_start, year_end, incremental, result
                )
        else:
            # BaoStock 同 session 不支持并发查询,需要每线程独立 login
            # 简化:序列化(rate-limit 友好);后续若需并行,改为多 adapter
            logger.warning("BaoStock 不支持并发,强制 max_workers=1")
            for idx, code in enumerate(codes, 1):
                _progress.current_index = idx
                _progress.current_code = code
                _process_one(
                    adapter, repo, code, year_start, year_end, incremental, result
                )
    finally:
        adapter.logout()

    result.elapsed_sec = round(time.time() - t0, 2)
    _progress.status = "completed"
    _progress.finished_at = datetime.now().isoformat()
    _progress.result = asdict(result)

    logger.info(
        f"[A dividend] Done: updated={result.updated} skipped={result.skipped} "
        f"failed={result.failed} elapsed={result.elapsed_sec}s"
    )
    return result


def _process_one(
    adapter,
    repo,
    code: str,
    year_start: int,
    year_end: int,
    incremental: bool,
    result: DividendUpdateResult,
) -> None:
    """处理单只股票的 dividend 抓取与写入。错误不抛出,累加到 result。"""
    try:
        if incremental:
            latest = _latest_dividend_year(repo, code)
            # 增量补抓:从 latest 当年(覆盖年中可能新派的)到 year_end
            start = latest if latest else year_start
        else:
            start = year_start

        if start > year_end:
            result.skipped += 1
            return

        new_records = _fetch_dividend_years(adapter, code, start, year_end)

        if not new_records:
            result.skipped += 1
            return

        if incremental and start <= year_end:
            # 增量模式:合并旧数据 + 新数据,按 dividOperateDate 去重
            try:
                existing = repo.read_dividends(code)
            except FileNotFoundError:
                existing = []
            # 用 dividOperateDate 作为 key 去重(新记录覆盖旧记录)
            merged_map = {r.dividOperateDate: r for r in existing}
            for r in new_records:
                merged_map[r.dividOperateDate] = r
            final_records = list(merged_map.values())
        else:
            final_records = new_records

        repo.write_dividends(code, final_records)
        result.updated += 1

    except Exception as e:
        result.failed += 1
        if len(result.errors) < 50:
            result.errors.append(f"{code}: {e}")
        logger.error(f"[A dividend] Failed {code}: {e}")
