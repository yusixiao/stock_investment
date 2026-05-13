import time
import logging
from pathlib import Path
from typing import Callable
from datetime import datetime, date
from concurrent.futures import TimeoutError as FutureTimeout

import akshare as ak
import pandas as pd

from config import FINANCIAL_DIR, LOG_DIR

logger = logging.getLogger(__name__)

COLUMNS = [
    "股票代码",
    "股票简称",
    "每股收益",
    "营业总收入-营业总收入",
    "营业总收入-同比增长",
    "营业总收入-季度环比增长",
    "净利润-净利润",
    "净利润-同比增长",
    "净利润-季度环比增长",
    "每股净资产",
    "净资产收益率",
    "每股经营现金流量",
    "销售毛利率",
    "所处行业",
    "最新公告日期",
]

SLEEP_BETWEEN_CALLS = 1.0
API_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_WAIT = 5

FINANCIAL_PROGRESS_FILE = LOG_DIR / "financial_progress.log"


def _log_progress(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(FINANCIAL_PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _call_api(date_str: str) -> pd.DataFrame:
    return ak.stock_yjbb_em(date=date_str)


def _run_with_timeout(fn, *args):
    from services.api_utils import run_with_timeout

    return run_with_timeout(fn, *args, timeout=API_TIMEOUT)


def generate_quarter_dates(
    start_year: int = 2000, end_date: date | None = None
) -> list[str]:
    if end_date is None:
        end_date = date.today()
    quarter_ends = ["0331", "0630", "0930", "1231"]
    result = []
    for y in range(start_year, end_date.year + 1):
        for q in quarter_ends:
            d = f"{y}{q}"
            if int(d) <= int(end_date.strftime("%Y%m%d")):
                result.append(d)
    return result


def fetch_quarter(date_str: str) -> pd.DataFrame | None:
    for attempt in range(MAX_RETRIES):
        try:
            df = _run_with_timeout(_call_api, date_str)
            if df is None or df.empty:
                return None
            return df
        except FutureTimeout:
            logger.warning(f"获取 {date_str} 业绩报表超时 (第{attempt + 1}次)")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            logger.warning(f"获取 {date_str} 业绩报表失败 (第{attempt + 1}次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
    return None


def _normalize_symbol(code: str) -> str:
    code = str(code).strip()
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    elif code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _quarter_to_date_str(q: str) -> str:
    return f"{q[:4]}-{q[4:6]}-{q[6:]}"


def split_and_save(df: pd.DataFrame, quarter_date: str, financial_dir: Path) -> dict:
    saved = 0
    quarter_date_str = _quarter_to_date_str(quarter_date)
    for _, row in df.iterrows():
        code = str(row["股票代码"]).strip()
        if len(code) != 6:
            continue
        symbol = _normalize_symbol(code)
        filepath = financial_dir / f"{symbol}.parquet"

        row_data = {}
        row_data["报告期"] = quarter_date_str
        for col in COLUMNS:
            if col in df.columns:
                row_data[col] = row[col]
        new_row = pd.DataFrame([row_data])

        if filepath.exists():
            existing = pd.read_parquet(filepath)
            existing = existing[existing["报告期"] != quarter_date_str]
            merged = pd.concat([new_row, existing], ignore_index=True)
            merged = merged.sort_values("报告期", ascending=False).reset_index(
                drop=True
            )
            merged.to_parquet(filepath, index=False)
        else:
            new_row.to_parquet(filepath, index=False)
        saved += 1
    return {"saved": saved}


def get_existing_quarters(financial_dir: Path) -> set[str]:
    quarters = set()
    for f in financial_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(f, columns=["报告期"])
            for d in df["报告期"].dropna().unique():
                ds = str(d).replace("-", "")[:8]
                quarters.add(ds)
        except Exception:
            continue
        break
    return quarters


def run_financial_update(
    mode: str = "full",
    financial_dir: Path | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    if financial_dir is None:
        financial_dir = FINANCIAL_DIR
    financial_dir.mkdir(parents=True, exist_ok=True)

    all_quarters = generate_quarter_dates()

    if mode == "incremental":
        existing = get_existing_quarters(financial_dir)
        recent_4 = all_quarters[-4:] if len(all_quarters) >= 4 else all_quarters
        quarters = [q for q in recent_4 if q not in existing]
        if not quarters:
            quarters = all_quarters[-1:]
    else:
        quarters = all_quarters

    total = len(quarters)
    success = 0
    failed = 0
    skipped = 0
    errors = []
    total_saved = 0

    FINANCIAL_PROGRESS_FILE.write_text("", encoding="utf-8")
    _log_progress(f"开始{mode}更新财报数据, 共 {total} 个季度")

    for i, q in enumerate(quarters, 1):
        if on_progress:
            on_progress(i, total, f"拉取财报数据 {q}")

        df = fetch_quarter(q)
        if df is None:
            failed += 1
            errors.append(q)
            _log_progress(f"[失败] {q}")
        else:
            result = split_and_save(df, q, financial_dir)
            total_saved += result["saved"]
            success += 1

        if i % 10 == 0 or i == total:
            _log_progress(
                f"进度 {i}/{total} — 成功:{success} 失败:{failed} 写入:{total_saved}条"
            )

        time.sleep(SLEEP_BETWEEN_CALLS)

    _log_progress(f"完成! 成功:{success} 失败:{failed} 写入:{total_saved}条")
    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "total": total,
        "total_saved": total_saved,
    }
