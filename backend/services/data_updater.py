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
    QFQ_KLINE_DIR,
    UPDATE_LOG_FILE,
    UPDATE_PROGRESS_FILE,
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


def map_spot_to_record(row: pd.Series, today_str: str) -> dict:
    code = str(row["代码"])
    return {
        "date": today_str,
        "open": float(row["今开"]),
        "high": float(row["最高"]),
        "low": float(row["最低"]),
        "close": float(row["最新价"]),
        "volume": float(row["成交量"]),
        "amount": float(row["成交额"]),
        "_code": code,
        "_exchange": symbol_to_exchange(code),
    }


def retry_fetch_spot(max_attempts: int = RETRY_MAX_ATTEMPTS, progress_callback=None) -> pd.DataFrame:
    last_error = None
    for attempt in range(max_attempts):
        try:
            df = ak.stock_zh_a_spot_em()
            return df
        except Exception as e:
            last_error = e
            wait = min(2 ** attempt, RETRY_BACKOFF_CAP)
            msg = f"API 调用失败 (第{attempt+1}/{max_attempts}次), {wait}s 后重试: {e}"
            logger.warning(msg)
            if progress_callback:
                progress_callback(msg)
            time.sleep(wait)
    raise RuntimeError(f"{max_attempts} 次重试后仍然失败: {last_error}")


def run_incremental_update(
    data_dir: Optional[Path] = None,
    today_str: Optional[str] = None,
    trigger: str = "manual",
) -> UpdateResult:
    if data_dir is None:
        data_dir = RAW_KLINE_DIR
    if today_str is None:
        today_str = date.today().strftime("%Y-%m-%d")

    result = UpdateResult(trigger=trigger, started_at=datetime.now().isoformat())
    updated_symbols: list[str] = []

    def _log_progress(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        with open(UPDATE_PROGRESS_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

    UPDATE_PROGRESS_FILE.write_text("", encoding="utf-8")
    _log_progress(f"开始更新 trigger={trigger} date={today_str}")

    t0 = time.time()
    _log_progress("正在调用 AKShare API 获取全量行情...")
    try:
        spot_df = retry_fetch_spot(progress_callback=_log_progress)
    except RuntimeError as e:
        _log_progress(f"API 调用最终失败: {e}")
        raise
    result.api_elapsed_sec = round(time.time() - t0, 2)
    total = len(spot_df)
    _log_progress(f"API 返回 {total} 只股票, 耗时 {result.api_elapsed_sec}s")

    for idx, (_, row) in enumerate(spot_df.iterrows(), 1):
        try:
            record = map_spot_to_record(row, today_str)
            code = record.pop("_code")
            exchange = record.pop("_exchange")
            filename = f"{code}.{exchange}.parquet"
            filepath = data_dir / filename

            if filepath.exists():
                existing = pd.read_parquet(filepath)
                latest_date = existing.iloc[0]["date"] if not existing.empty else ""
                if today_str <= latest_date:
                    result.skipped += 1
                    continue
                new_row = pd.DataFrame([record])
                merged = pd.concat([new_row, existing], ignore_index=True)
                merged.to_parquet(filepath, index=False)
                result.updated += 1
                updated_symbols.append(f"{code}.{exchange}")
            else:
                new_df = pd.DataFrame([record])
                new_df.to_parquet(filepath, index=False)
                result.new_stocks += 1
                updated_symbols.append(f"{code}.{exchange}")
        except Exception as e:
            result.failed += 1
            result.errors.append(f"{row.get('代码', '?')}: {e}")
            logger.error(f"Failed to update {row.get('代码', '?')}: {e}")

        if idx % 500 == 0 or idx == total:
            _log_progress(f"进度 {idx}/{total} — 更新:{result.updated} 跳过:{result.skipped} 新增:{result.new_stocks} 失败:{result.failed}")

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
