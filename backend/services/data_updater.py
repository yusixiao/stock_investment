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
from services.qfq_cache import invalidate_cache

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
    path = tracker_path or STOCK_UPDATE_TRACKER_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_tracker(tracker: dict, tracker_path: Path = None):
    path = tracker_path or STOCK_UPDATE_TRACKER_FILE
    path.write_text(json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_hist_with_retry(symbol: str, start_date: str, end_date: str, max_attempts: int = RETRY_MAX_ATTEMPTS) -> pd.DataFrame:
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
            wait = min(2 ** attempt, RETRY_BACKOFF_CAP)
            time.sleep(wait)
    raise RuntimeError(f"{symbol} {max_attempts}次重试失败: {last_error}")


def _hist_df_to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        records.append({
            "date": str(row["日期"])[:10],
            "open": float(row["开盘"]),
            "high": float(row["最高"]),
            "low": float(row["最低"]),
            "close": float(row["收盘"]),
            "volume": float(row["成交量"]),
            "amount": float(row["成交额"]),
        })
    return records


def run_incremental_update(
    data_dir: Optional[Path] = None,
    trigger: str = "manual",
    tracker_path: Optional[Path] = None,
) -> UpdateResult:
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

    t0 = time.time()

    existing_files = list(data_dir.glob("*.parquet"))
    symbols = []
    for f in existing_files:
        stem = f.stem
        code = stem.split(".")[0]
        symbols.append((code, stem))

    if not symbols:
        _log_progress("未找到任何已有 parquet 文件，使用 stock_zh_a_spot_em 获取股票列表...")
        try:
            spot_df = ak.stock_zh_a_spot_em()
            for _, row in spot_df.iterrows():
                code = str(row["代码"])
                exchange = symbol_to_exchange(code)
                symbols.append((code, f"{code}.{exchange}"))
        except Exception as e:
            _log_progress(f"获取股票列表失败: {e}")
            raise

    total = len(symbols)
    _log_progress(f"共 {total} 只股票待检查")

    for idx, (code, full_symbol) in enumerate(symbols, 1):
        try:
            last_updated = tracker.get(full_symbol)

            if last_updated and last_updated >= end_date:
                result.skipped += 1
                if idx % 500 == 0 or idx == total:
                    _log_progress(f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}")
                continue

            if last_updated:
                next_day = (datetime.strptime(last_updated, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                sym_start = next_day
            else:
                sym_start = "2010-01-04"

            if sym_start > end_date:
                result.skipped += 1
                if idx % 500 == 0 or idx == total:
                    _log_progress(f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}")
                continue

            sym_start_fmt = sym_start.replace("-", "")
            filepath = data_dir / f"{full_symbol}.parquet"

            hist_df = _fetch_hist_with_retry(code, sym_start_fmt, end_date_fmt, max_attempts=3)

            if hist_df.empty:
                tracker[full_symbol] = end_date
                result.skipped += 1
                if idx % 500 == 0 or idx == total:
                    _log_progress(f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 失败:{result.failed}")
                continue

            new_records = _hist_df_to_records(hist_df)

            if filepath.exists():
                existing = pd.read_parquet(filepath)
                existing_dates = set(existing["date"].tolist())
                fresh = [r for r in new_records if r["date"] not in existing_dates]
                if not fresh:
                    tracker[full_symbol] = end_date
                    result.skipped += 1
                else:
                    fresh_df = pd.DataFrame(fresh)
                    merged = pd.concat([fresh_df, existing], ignore_index=True)
                    merged = merged.sort_values("date", ascending=False).reset_index(drop=True)
                    merged.to_parquet(filepath, index=False)
                    result.updated += 1
                    updated_symbols.append(full_symbol)
                    tracker[full_symbol] = end_date
            else:
                new_df = pd.DataFrame(new_records)
                new_df = new_df.sort_values("date", ascending=False).reset_index(drop=True)
                new_df.to_parquet(filepath, index=False)
                result.new_stocks += 1
                updated_symbols.append(full_symbol)
                tracker[full_symbol] = end_date

        except Exception as e:
            result.failed += 1
            if len(result.errors) < 50:
                result.errors.append(f"{code}: {e}")
            logger.error(f"Failed to update {code}: {e}")

        if idx % 500 == 0 or idx == total:
            _log_progress(f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 新增:{result.new_stocks} 失败:{result.failed}")

        if idx % 100 == 0:
            _save_tracker(tracker, tracker_path)

    _save_tracker(tracker, tracker_path)

    if updated_symbols:
        invalidate_cache(updated_symbols)
        _log_progress(f"已清除 {len(updated_symbols)} 只股票的 qfq 缓存")

    result.api_elapsed_sec = round(time.time() - t0, 2)
    result.finished_at = datetime.now().isoformat()
    elapsed = round(time.time() - t0, 2)
    _log_progress(f"完成! 更新:{result.updated} 跳过:{result.skipped} 新增:{result.new_stocks} 失败:{result.failed} 总耗时:{elapsed}s")
    _save_log(result)
    return result


def _save_log(result: UpdateResult) -> None:
    logs = []
    if UPDATE_LOG_FILE.exists():
        try:
            logs = json.loads(UPDATE_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            logs = []

    logs.insert(0, asdict(result))

    cutoff = (datetime.now() - timedelta(days=LOG_RETENTION_DAYS)).isoformat()
    logs = [l for l in logs if l.get("started_at", "") >= cutoff]

    UPDATE_LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


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
