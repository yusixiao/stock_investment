import time
import logging
import signal
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import akshare as ak
import pandas as pd

from datetime import datetime
from config import VALUATION_DIR, RAW_KLINE_DIR, LOG_DIR

logger = logging.getLogger(__name__)

INDICATOR_MAP = {
    "总市值": "total_mv",
    "市盈率(TTM)": "pe_ttm",
    "市盈率(静)": "pe_static",
    "市净率": "pb",
    "市现率": "pcf",
}

SLEEP_BETWEEN_CALLS = 0.5
API_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_WAIT = 5


def _call_api(symbol: str, indicator: str, period: str) -> pd.DataFrame:
    return ak.stock_zh_valuation_baidu(symbol=symbol, indicator=indicator, period=period)


def _run_with_timeout(fn, *args):
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(fn, *args)
        return future.result(timeout=API_TIMEOUT)
    except FutureTimeout:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    except Exception:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=False)


def fetch_single_indicator(
    symbol: str, indicator: str, col_name: str, period: str
) -> pd.DataFrame | None:
    for attempt in range(MAX_RETRIES):
        try:
            df = _run_with_timeout(_call_api, symbol, indicator, period)
            df = df.rename(columns={"value": col_name})
            return df[["date", col_name]]
        except FutureTimeout:
            logger.warning(f"获取 {symbol} {indicator} 超时 (第{attempt+1}次)")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            logger.warning(f"获取 {symbol} {indicator} 失败 (第{attempt+1}次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_WAIT)
    return None


def fetch_symbol_valuation(symbol: str, period: str) -> pd.DataFrame | None:
    code = symbol.split(".")[0]
    dfs = []
    for indicator, col_name in INDICATOR_MAP.items():
        df = fetch_single_indicator(code, indicator, col_name, period)
        if df is not None:
            dfs.append(df)
        time.sleep(SLEEP_BETWEEN_CALLS)
    if not dfs:
        return None
    merged = dfs[0]
    for df in dfs[1:]:
        merged = merged.merge(df, on="date", how="outer")
    merged = merged.sort_values("date", ascending=False).reset_index(drop=True)
    time.sleep(SLEEP_BETWEEN_CALLS)
    return merged


def get_all_symbols() -> list[str]:
    return [f.stem for f in sorted(RAW_KLINE_DIR.glob("*.parquet"))]


VALUATION_PROGRESS_FILE = LOG_DIR / "valuation_progress.log"


def _log_progress(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with open(VALUATION_PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def run_valuation_update(
    mode: str = "full",
    symbols: list[str] | None = None,
    valuation_dir: Path | None = None,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    if valuation_dir is None:
        valuation_dir = VALUATION_DIR
    valuation_dir.mkdir(parents=True, exist_ok=True)

    if symbols is None:
        symbols = get_all_symbols()

    total = len(symbols)
    success = 0
    skipped = 0
    failed = 0
    errors = []

    VALUATION_PROGRESS_FILE.write_text("", encoding="utf-8")
    _log_progress(f"开始{mode}更新估值数据, 共 {total} 只股票")

    for i, sym in enumerate(symbols, 1):
        filepath = valuation_dir / f"{sym}.parquet"

        if mode == "full":
            if filepath.exists() and not force:
                skipped += 1
                if on_progress:
                    on_progress(i, total, "拉取估值数据")
                continue
            df = fetch_symbol_valuation(sym, "全部")
            if df is None:
                failed += 1
                errors.append(sym)
                _log_progress(f"[失败] {sym}")
            else:
                df.to_parquet(filepath, index=False)
                success += 1

        elif mode == "incremental":
            if not filepath.exists():
                skipped += 1
                if on_progress:
                    on_progress(i, total, "增量更新估值数据")
                continue
            existing = pd.read_parquet(filepath)
            latest_date = existing.iloc[0]["date"] if not existing.empty else ""
            new_df = fetch_symbol_valuation(sym, "近一年")
            if new_df is None:
                failed += 1
                errors.append(sym)
                _log_progress(f"[失败] {sym}")
            else:
                new_rows = new_df[new_df["date"] > latest_date]
                if not new_rows.empty:
                    merged = pd.concat([new_rows, existing], ignore_index=True)
                    merged = merged.sort_values("date", ascending=False).reset_index(drop=True)
                    merged.to_parquet(filepath, index=False)
                success += 1

        if on_progress:
            phase = "拉取估值数据" if mode == "full" else "增量更新估值数据"
            on_progress(i, total, phase)

        if i % 100 == 0 or i == total:
            _log_progress(f"进度 {i}/{total} — 成功:{success} 跳过:{skipped} 失败:{failed}")

    _log_progress(f"完成! 成功:{success} 跳过:{skipped} 失败:{failed}")
    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "total": total,
    }
