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
    LOG_RETENTION_DAYS,
    RETRY_MAX_ATTEMPTS,
    RETRY_BACKOFF_CAP,
)
from services.stock_data import symbol_to_exchange

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


def retry_fetch_spot(max_attempts: int = RETRY_MAX_ATTEMPTS) -> pd.DataFrame:
    last_error = None
    for attempt in range(max_attempts):
        try:
            df = ak.stock_zh_a_spot_em()
            return df
        except Exception as e:
            last_error = e
            wait = min(2 ** attempt, RETRY_BACKOFF_CAP)
            logger.warning(f"API call failed (attempt {attempt+1}/{max_attempts}), retry in {wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError(f"20 次重试后仍然失败: {last_error}")


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

    t0 = time.time()
    spot_df = retry_fetch_spot()
    result.api_elapsed_sec = round(time.time() - t0, 2)

    for _, row in spot_df.iterrows():
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
            else:
                new_df = pd.DataFrame([record])
                new_df.to_parquet(filepath, index=False)
                result.new_stocks += 1
        except Exception as e:
            result.failed += 1
            result.errors.append(f"{row.get('代码', '?')}: {e}")
            logger.error(f"Failed to update {row.get('代码', '?')}: {e}")

    result.finished_at = datetime.now().isoformat()
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
