import time
import logging
from pathlib import Path
from typing import Callable
from datetime import datetime
from concurrent.futures import TimeoutError as FutureTimeout

import akshare as ak
import pandas as pd

from config import DIVIDEND_DIR, LOG_DIR

logger = logging.getLogger(__name__)

EM_COLUMNS = [
    "报告期",
    "业绩披露日期",
    "送转股份-送转总比例",
    "送转股份-送股比例",
    "送转股份-转股比例",
    "现金分红-现金分红比例",
    "现金分红-现金分红比例描述",
    "现金分红-股息率",
    "每股收益",
    "每股净资产",
    "每股公积金",
    "每股未分配利润",
    "净利润同比增长",
    "总股本",
    "预案公告日",
    "股权登记日",
    "除权除息日",
    "方案进度",
    "最新公告日期",
]

SINA_TO_EM_MAP = {
    "送股": "送转股份-送股比例",
    "转增": "送转股份-转股比例",
    "派息": "现金分红-现金分红比例",
    "公告日期": "预案公告日",
    "股权登记日": "股权登记日",
    "除权除息日": "除权除息日",
    "进度": "方案进度",
}

SLEEP_BETWEEN_CALLS = 0.5
API_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_WAIT = 5

DIVIDEND_PROGRESS_FILE = LOG_DIR / "dividend_progress.log"


def _log_progress(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(DIVIDEND_PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _call_em_api(symbol: str) -> pd.DataFrame:
    return ak.stock_fhps_detail_em(symbol=symbol)


def _call_sina_api(symbol: str) -> pd.DataFrame:
    return ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")


def _run_with_timeout(fn, *args):
    from services.api_utils import run_with_timeout

    return run_with_timeout(fn, *args, timeout=API_TIMEOUT)


def fetch_dividend_em(symbol: str) -> pd.DataFrame | None:
    for attempt in range(MAX_RETRIES):
        try:
            df = _run_with_timeout(_call_em_api, symbol)
            for col in EM_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            return df[EM_COLUMNS]
        except FutureTimeout:
            logger.warning(f"东方财富 {symbol} 超时 (第{attempt + 1}次)")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            logger.warning(f"东方财富 {symbol} 失败 (第{attempt + 1}次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
    return None


def fetch_dividend_sina(symbol: str) -> pd.DataFrame | None:
    for attempt in range(MAX_RETRIES):
        try:
            df = _run_with_timeout(_call_sina_api, symbol)
            return df
        except FutureTimeout:
            logger.warning(f"新浪 {symbol} 超时 (第{attempt + 1}次)")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            logger.warning(f"新浪 {symbol} 失败 (第{attempt + 1}次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
    return None


def map_sina_to_em(sina_df: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(columns=EM_COLUMNS)
    for sina_col, em_col in SINA_TO_EM_MAP.items():
        if sina_col in sina_df.columns:
            result[em_col] = sina_df[sina_col].values
    send = result["送转股份-送股比例"].fillna(0)
    transfer = result["送转股份-转股比例"].fillna(0)
    result["送转股份-送转总比例"] = send + transfer
    return result


def fetch_symbol_dividend(symbol: str) -> pd.DataFrame | None:
    code = symbol.split(".")[0]
    df = fetch_dividend_em(code)
    if df is not None:
        return df
    logger.info(f"{symbol} 东方财富失败, 尝试新浪fallback")
    sina_df = fetch_dividend_sina(code)
    if sina_df is not None:
        return map_sina_to_em(sina_df)
    return None


def get_all_symbols() -> list[str]:
    """从 DuckDB 取 A 股全市场代码列表(已按代码排序)。"""
    from services.duckdb_store import get_store

    return get_store().list_symbols("A")


def run_dividend_update(
    mode: str = "full",
    symbols: list[str] | None = None,
    dividend_dir: Path | None = None,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    if dividend_dir is None:
        dividend_dir = DIVIDEND_DIR
    dividend_dir.mkdir(parents=True, exist_ok=True)

    if symbols is None:
        symbols = get_all_symbols()

    total = len(symbols)
    success = 0
    skipped = 0
    failed = 0
    errors = []
    updated_symbols = []

    DIVIDEND_PROGRESS_FILE.write_text("", encoding="utf-8")
    _log_progress(f"开始{mode}更新分红数据, 共 {total} 只股票")

    for i, sym in enumerate(symbols, 1):
        filepath = dividend_dir / f"{sym}.parquet"

        if mode == "full":
            if filepath.exists() and not force:
                skipped += 1
                if on_progress:
                    on_progress(i, total, "拉取分红数据")
                continue
            df = fetch_symbol_dividend(sym)
            if df is None:
                failed += 1
                errors.append(sym)
                _log_progress(f"[失败] {sym}")
            else:
                df.to_parquet(filepath, index=False)
                success += 1
                updated_symbols.append(sym)

        elif mode == "incremental":
            if not filepath.exists():
                skipped += 1
                if on_progress:
                    on_progress(i, total, "增量更新分红数据")
                continue
            existing = pd.read_parquet(filepath)
            new_df = fetch_symbol_dividend(sym)
            if new_df is None:
                failed += 1
                errors.append(sym)
                _log_progress(f"[失败] {sym}")
            else:
                key_col = (
                    "报告期" if "报告期" in existing.columns else existing.columns[0]
                )
                merged = pd.concat([new_df, existing], ignore_index=True)
                merged = merged.drop_duplicates(subset=[key_col], keep="first")
                merged = merged.sort_values(key_col, ascending=False).reset_index(
                    drop=True
                )
                merged.to_parquet(filepath, index=False)
                success += 1
                updated_symbols.append(sym)

        if on_progress:
            phase = "拉取分红数据" if mode == "full" else "增量更新分红数据"
            on_progress(i, total, phase)

        if i % 100 == 0 or i == total:
            _log_progress(
                f"进度 {i}/{total} — 成功:{success} 跳过:{skipped} 失败:{failed}"
            )

        time.sleep(SLEEP_BETWEEN_CALLS)

    _log_progress(f"完成! 成功:{success} 跳过:{skipped} 失败:{failed}")
    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "total": total,
    }
