"""
批量迁移 BaoStock K线 + 复权因子（单次登录，直接 DataFrame 写入）

用法:
    python scripts/migrate_kline_batch.py
    python scripts/migrate_kline_batch.py --offset 100
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import baostock as bs
import pandas as pd


class TimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise TimeoutError("BaoStock请求超时")


FETCH_TIMEOUT = 60

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import RAW_KLINE_DIR, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NEW_DAILY_DIR = DATA_DIR / "market" / "A" / "daily"
NEW_ADJUST_FACTOR_DIR = DATA_DIR / "market" / "A" / "adjust_factor"

KLINE_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)

FLOAT_COLS = [
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "pctChg",
    "peTTM",
    "pbMRQ",
    "psTTM",
    "pcfNcfTTM",
]


def to_bs_code(code: str) -> str:
    parts = code.split(".")
    return f"{parts[1].lower()}.{parts[0]}"


def result_to_df(rs) -> pd.DataFrame:
    rows = []
    while (rs.error_code == "0") and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=rs.fields)


def fetch_and_save_kline(code: str) -> int:
    """直接用 DataFrame 写入 parquet，跳过逐行 Pydantic 验证"""
    bs_code = to_bs_code(code)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(FETCH_TIMEOUT)
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            KLINE_FIELDS,
            start_date="1990-01-01",
            end_date="2026-12-31",
            frequency="d",
            adjustflag="3",
        )
        df = result_to_df(rs)
    finally:
        signal.alarm(0)

    if df.empty:
        return 0

    for col in FLOAT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["code"] = code
    df["volume"] = df["volume"].fillna(0.0)
    df["amount"] = df["amount"].fillna(0.0)

    out_path = NEW_DAILY_DIR / f"{code}.parquet"
    df.to_parquet(out_path, index=False)
    return len(df)


def fetch_and_save_factor(code: str) -> int:
    bs_code = to_bs_code(code)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(FETCH_TIMEOUT)
    try:
        rs = bs.query_adjust_factor(code=bs_code)
        df = result_to_df(rs)
    finally:
        signal.alarm(0)
    if df.empty:
        return 0

    df["foreAdjustFactor"] = pd.to_numeric(df["foreAdjustFactor"], errors="coerce")
    if "backAdjustFactor" in df.columns:
        df["backAdjustFactor"] = pd.to_numeric(df["backAdjustFactor"], errors="coerce")
    if "adjustFactor" in df.columns:
        df["adjustFactor"] = pd.to_numeric(df["adjustFactor"], errors="coerce")
    df["code"] = code

    out_path = NEW_ADJUST_FACTOR_DIR / f"{code}.parquet"
    df.to_parquet(out_path, index=False)
    return len(df)


def main(offset: int = 0):
    NEW_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    NEW_ADJUST_FACTOR_DIR.mkdir(parents=True, exist_ok=True)

    codes = sorted([f.stem for f in RAW_KLINE_DIR.glob("*.parquet") if f.stem])
    total = len(codes)
    codes = codes[offset:]

    logger.info(f"总股票数: {total}, 从 offset={offset} 开始, 剩余 {len(codes)} 只")

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"BaoStock login failed: {lg.error_msg}")
        return
    logger.info("BaoStock 登录成功")

    success = 0
    fail = 0
    empty = 0
    skipped = 0
    failed_codes = []
    start_time = time.time()

    relogin_interval = 300
    consecutive_empty = 0

    try:
        for i, code in enumerate(codes):
            idx = offset + i
            if (idx + 1) % 100 == 0:
                elapsed = time.time() - start_time
                speed = (i + 1) / elapsed * 3600
                logger.info(
                    f"进度: {idx + 1}/{total} | 成功={success} 空={empty} 失败={fail} 跳过={skipped} | {speed:.0f} 只/小时"
                )

            out_path = NEW_DAILY_DIR / f"{code}.parquet"
            if out_path.exists():
                skipped += 1
                continue

            if (i + 1) % relogin_interval == 0 or consecutive_empty >= 50:
                bs.logout()
                time.sleep(1)
                lg2 = bs.login()
                if lg2.error_code != "0":
                    logger.error(f"重新登录失败: {lg2.error_msg}")
                    break
                if consecutive_empty >= 50:
                    logger.info(f"连续{consecutive_empty}只空数据，已重新登录")
                consecutive_empty = 0

            try:
                logger.info(f"[{idx + 1}/{total}] 获取 {code} ...")
                n = fetch_and_save_kline(code)
                if n > 0:
                    fetch_and_save_factor(code)
                    success += 1
                    consecutive_empty = 0
                    logger.info(f"  {code} 完成: {n} 行K线")
                else:
                    empty += 1
                    consecutive_empty += 1
                    logger.info(f"  {code} 空数据")
            except Exception as e:
                fail += 1
                consecutive_empty += 1
                failed_codes.append(code)
                logger.warning(f"  {code} 失败: {e}")

    except KeyboardInterrupt:
        logger.info(f"\n手动中断于 offset={idx}")
    finally:
        bs.logout()
        elapsed = time.time() - start_time
        logger.info(f"\n===== 迁移统计 =====")
        logger.info(f"成功: {success} | 空: {empty} | 失败: {fail} | 跳过: {skipped}")
        logger.info(f"耗时: {elapsed / 60:.1f} 分钟")
        logger.info(
            f"断点续传命令: python scripts/migrate_kline_batch.py --offset {idx + 1}"
        )
        if failed_codes:
            failed_file = DATA_DIR / "logs" / "migrate_kline_failed.txt"
            with open(failed_file, "w") as f:
                f.write("\n".join(failed_codes))
            logger.info(f"失败列表已写入: {failed_file} ({len(failed_codes)} 只)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    main(offset=args.offset)
