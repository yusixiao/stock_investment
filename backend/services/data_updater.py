"""
数据增量更新服务。

核心逻辑：基于 tracker 文件记录每只股票最后更新日期，
仅拉取 last_updated+1 ~ today 的增量数据，合并到 parquet 文件。
"""

import time
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List

import akshare as ak
import pandas as pd

from config import (
    RAW_KLINE_DIR,
    UPDATE_LOG_FILE,
    UPDATE_PROGRESS_FILE,
    STOCK_UPDATE_TRACKER_FILE,
    LOG_RETENTION_DAYS,
    RETRY_MAX_ATTEMPTS,
    RETRY_BACKOFF_CAP,
)
from services.stock_data import symbol_to_exchange
from services.indicator_store import compute_and_save

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    new_stocks: int = 0
    errors: List[str] = field(default_factory=list)
    api_retries: int = 0
    api_elapsed_sec: float = 0.0
    trigger: str = "manual"
    started_at: str = ""
    finished_at: str = ""


def _load_tracker(tracker_path: Path = None) -> dict:
    """加载 tracker JSON：记录每只股票上次成功更新的日期，用于增量判断。"""
    path = tracker_path or STOCK_UPDATE_TRACKER_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Tracker 文件解析失败，将从空 tracker 开始")
            return {}
    return {}


def _save_tracker(tracker: dict, tracker_path: Path = None):
    """持久化 tracker，每 100 只股票保存一次防止中断丢失进度。"""
    path = tracker_path or STOCK_UPDATE_TRACKER_FILE
    path.write_text(json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_hist_with_retry(
    symbol: str, start_date: str, end_date: str, max_attempts: int = RETRY_MAX_ATTEMPTS
) -> pd.DataFrame:
    """
    带指数退避重试的 AKShare API 调用。
    重试机制：每次失败后等待 min(2^attempt, RETRY_BACKOFF_CAP) 秒，
    最多尝试 max_attempts 次，全部失败则抛出 RuntimeError。
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            )
            return df
        except Exception as e:
            last_error = e
            wait = min(2**attempt, RETRY_BACKOFF_CAP)
            logger.warning(
                f"API 调用失败 symbol={symbol} attempt={attempt + 1}/{max_attempts}, "
                f"等待 {wait}s 后重试: {e}"
            )
            time.sleep(wait)
    logger.error(
        f"API 调用彻底失败 symbol={symbol}, 已重试 {max_attempts} 次: {last_error}"
    )
    raise RuntimeError(f"{symbol} {max_attempts}次重试失败: {last_error}")


def _hist_df_to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        records.append(
            {
                "date": str(row["日期"])[:10],
                "open": float(row["开盘"]),
                "high": float(row["最高"]),
                "low": float(row["最低"]),
                "close": float(row["收盘"]),
                "volume": float(row["成交量"]),
                "amount": float(row["成交额"]),
            }
        )
    return records


def run_incremental_update(
    data_dir: Optional[Path] = None,
    trigger: str = "manual",
    tracker_path: Optional[Path] = None,
) -> UpdateResult:
    """
    增量更新主函数。

    增量逻辑：
    1. 加载 tracker（JSON dict: {symbol: last_updated_date}）
    2. 对每只股票，若 tracker 中记录的日期 >= 今天则跳过
    3. 否则从 last_updated + 1 天开始拉取增量数据
    4. 合并到已有 parquet 文件（去重 + 按日期降序排列）
    5. 更新 tracker 中该股票的日期为今天
    6. 每 100 只保存 tracker，防止中断丢失全部进度
    """
    if data_dir is None:
        data_dir = RAW_KLINE_DIR

    end_date = date.today().strftime("%Y-%m-%d")
    end_date_fmt = end_date.replace("-", "")

    tracker = _load_tracker(tracker_path)
    result = UpdateResult(trigger=trigger, started_at=datetime.now().isoformat())
    updated_symbols: list[str] = []

    def _log_progress(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        with open(UPDATE_PROGRESS_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

    UPDATE_PROGRESS_FILE.write_text("", encoding="utf-8")
    _log_progress(f"开始增量更新 trigger={trigger} end_date={end_date}")
    logger.info(f"开始增量更新 trigger={trigger} end_date={end_date}")

    t0 = time.time()

    # 收集待更新股票列表：优先从已有 parquet 文件获取，否则调用 API 拉全量列表
    existing_files = list(data_dir.glob("*.parquet"))
    symbols = []
    for f in existing_files:
        stem = f.stem
        code = stem.split(".")[0]
        symbols.append((code, stem))

    if not symbols:
        _log_progress(
            "未找到任何已有 parquet 文件，使用 stock_zh_a_spot_em 获取股票列表..."
        )
        logger.info("无已有数据文件，从 API 获取全量股票列表")
        try:
            spot_df = ak.stock_zh_a_spot_em()
            for _, row in spot_df.iterrows():
                code = str(row["代码"])
                exchange = symbol_to_exchange(code)
                symbols.append((code, f"{code}.{exchange}"))
        except Exception as e:
            _log_progress(f"获取股票列表失败: {e}")
            logger.error(f"获取股票列表失败，更新中止: {e}")
            raise

    total = len(symbols)
    _log_progress(f"共 {total} 只股票待检查")
    logger.info(f"共 {total} 只股票待检查更新")

    for idx, (code, full_symbol) in enumerate(symbols, 1):
        try:
            # 增量判断：tracker 中记录了该股票最后更新日期
            last_updated = tracker.get(full_symbol)

            # 若已更新到今天或更晚，直接跳过
            if last_updated and last_updated >= end_date:
                result.skipped += 1
                if idx % 500 == 0 or idx == total:
                    _log_progress(
                        f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}"
                    )
                continue

            # 计算增量起始日期：从上次更新的下一天开始拉取
            if last_updated:
                next_day = (
                    datetime.strptime(last_updated, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")
                sym_start = next_day
            else:
                # 无记录的股票从 2010 年开始全量拉取
                sym_start = "2010-01-04"

            if sym_start > end_date:
                result.skipped += 1
                if idx % 500 == 0 or idx == total:
                    _log_progress(
                        f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}"
                    )
                continue

            sym_start_fmt = sym_start.replace("-", "")
            filepath = data_dir / f"{full_symbol}.parquet"

            hist_df = _fetch_hist_with_retry(
                code, sym_start_fmt, end_date_fmt, max_attempts=3
            )

            if hist_df.empty:
                tracker[full_symbol] = end_date
                result.skipped += 1
                if idx % 500 == 0 or idx == total:
                    _log_progress(
                        f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}"
                    )
                continue

            new_records = _hist_df_to_records(hist_df)

            if filepath.exists():
                # 合并增量数据：去重（按 date）后按日期降序保存
                existing = pd.read_parquet(filepath)
                existing_dates = set(existing["date"].tolist())
                fresh = [r for r in new_records if r["date"] not in existing_dates]
                if not fresh:
                    tracker[full_symbol] = end_date
                    result.skipped += 1
                else:
                    fresh_df = pd.DataFrame(fresh)
                    merged = pd.concat([fresh_df, existing], ignore_index=True)
                    merged = merged.sort_values("date", ascending=False).reset_index(
                        drop=True
                    )
                    merged.to_parquet(filepath, index=False)
                    result.updated += 1
                    updated_symbols.append(full_symbol)
                    tracker[full_symbol] = end_date
            else:
                # 新股票：直接写入
                new_df = pd.DataFrame(new_records)
                new_df = new_df.sort_values("date", ascending=False).reset_index(
                    drop=True
                )
                new_df.to_parquet(filepath, index=False)
                result.new_stocks += 1
                updated_symbols.append(full_symbol)
                tracker[full_symbol] = end_date

        except Exception as e:
            result.failed += 1
            if len(result.errors) < 50:
                result.errors.append(f"{code}: {e}")
            logger.error(f"更新失败 {code}: {e}")

        # 每 100 只股票输出一次 INFO 日志便于监控
        if idx % 100 == 0:
            logger.info(
                f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}"
            )

        if idx % 500 == 0 or idx == total:
            _log_progress(
                f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 新增:{result.new_stocks} 失败:{result.failed}"
            )

        # 每 100 只持久化 tracker，防止进程中断导致全部进度丢失
        if idx % 100 == 0:
            _save_tracker(tracker, tracker_path)

    _save_tracker(tracker, tracker_path)

    result.api_elapsed_sec = round(time.time() - t0, 2)
    result.finished_at = datetime.now().isoformat()
    elapsed = round(time.time() - t0, 2)
    _log_progress(
        f"完成! 更新:{result.updated} 跳过:{result.skipped} 新增:{result.new_stocks} 失败:{result.failed} 总耗时:{elapsed}s"
    )
    logger.info(
        f"增量更新完成 — 更新:{result.updated} 跳过:{result.skipped} 新增:{result.new_stocks} "
        f"失败:{result.failed} 耗时:{elapsed}s"
    )
    _save_log(result)
    return result


def _save_log(result: UpdateResult) -> None:
    """保存更新日志到 JSON 文件，按 LOG_RETENTION_DAYS 自动清理旧记录。"""
    logs = []
    if UPDATE_LOG_FILE.exists():
        try:
            logs = json.loads(UPDATE_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    logs.insert(0, asdict(result))

    cutoff = (datetime.now() - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
    logs = [l for l in logs if l.get("started_at", "") >= cutoff]

    UPDATE_LOG_FILE.write_text(
        json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


_current_status: Optional[str] = None
_current_result: Optional[UpdateResult] = None


def get_update_status() -> dict:
    return {
        "status": _current_status or "idle",
        "result": asdict(_current_result) if _current_result else None,
    }


def get_update_logs(limit: int = 20) -> list:
    if not UPDATE_LOG_FILE.exists():
        return []
    try:
        logs = json.loads(UPDATE_LOG_FILE.read_text(encoding="utf-8"))
        return logs[:limit]
    except Exception:
        return []
