"""
K线数据增量更新 — 读取每只股票最后日期，从 BaoStock 获取增量数据追加写入

用法:
    python scripts/update_kline_daily.py
    python scripts/update_kline_daily.py --end-date 2026-05-13
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import baostock as bs
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "logs" / "update_kline.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

DAILY_DIR = DATA_DIR / "market" / "A" / "daily"
ADJUST_FACTOR_DIR = DATA_DIR / "market" / "A" / "adjust_factor"

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

FETCH_TIMEOUT = 30


class FetchTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise FetchTimeout("BaoStock请求超时")


def to_bs_code(code: str) -> str:
    parts = code.split(".")
    return f"{parts[1].lower()}.{parts[0]}"


def get_last_dates() -> dict:
    """读取所有股票的最后日期，返回 {code: last_date_str}"""
    result = {}
    for f in DAILY_DIR.glob("*.parquet"):
        code = f.stem
        df = pd.read_parquet(f, columns=["date"])
        if not df.empty:
            result[code] = df.iloc[-1]["date"]
    return result


def fetch_incremental_kline(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取增量K线数据"""
    bs_code = to_bs_code(code)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(FETCH_TIMEOUT)
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            KLINE_FIELDS,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    finally:
        signal.alarm(0)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=rs.fields)


def fetch_adjust_factor(code: str) -> pd.DataFrame:
    """获取最新复权因子（全量覆盖）"""
    bs_code = to_bs_code(code)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(FETCH_TIMEOUT)
    try:
        rs = bs.query_adjust_factor(code=bs_code)
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    finally:
        signal.alarm(0)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=rs.fields)


def main(end_date: str = None):
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"开始增量更新，目标日期: {end_date}")
    logger.info("读取各股票最后日期...")

    last_dates = get_last_dates()
    total = len(last_dates)
    logger.info(f"共 {total} 只股票需要检查")

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"BaoStock 登录失败: {lg.error_msg}")
        return
    logger.info("BaoStock 登录成功")

    updated = 0
    skipped = 0
    failed = 0
    failed_codes = []
    relogin_interval = 300
    consecutive_fail = 0
    start_time = time.time()

    codes = sorted(last_dates.keys())

    try:
        for i, code in enumerate(codes):
            last_date = last_dates[code]

            if last_date >= end_date:
                skipped += 1
                continue

            next_date = (
                datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")

            if (i + 1) % relogin_interval == 0 or consecutive_fail >= 20:
                bs.logout()
                time.sleep(1)
                lg2 = bs.login()
                if lg2.error_code != "0":
                    logger.error(f"重新登录失败: {lg2.error_msg}")
                    break
                if consecutive_fail >= 20:
                    logger.info(f"连续{consecutive_fail}次失败，已重新登录")
                consecutive_fail = 0

            try:
                df_new = fetch_incremental_kline(code, next_date, end_date)

                if df_new.empty:
                    skipped += 1
                    continue

                for col in FLOAT_COLS:
                    if col in df_new.columns:
                        df_new[col] = pd.to_numeric(df_new[col], errors="coerce")
                df_new["code"] = code
                df_new["volume"] = df_new["volume"].fillna(0.0)
                df_new["amount"] = df_new["amount"].fillna(0.0)

                existing_path = DAILY_DIR / f"{code}.parquet"
                df_old = pd.read_parquet(existing_path)
                df_merged = pd.concat([df_old, df_new], ignore_index=True)
                df_merged = df_merged.drop_duplicates(subset=["date"], keep="last")
                df_merged = df_merged.sort_values("date").reset_index(drop=True)
                df_merged.to_parquet(existing_path, index=False)

                df_factor = fetch_adjust_factor(code)
                if not df_factor.empty:
                    for col in ["foreAdjustFactor", "backAdjustFactor", "adjustFactor"]:
                        if col in df_factor.columns:
                            df_factor[col] = pd.to_numeric(
                                df_factor[col], errors="coerce"
                            )
                    df_factor["code"] = code
                    factor_path = ADJUST_FACTOR_DIR / f"{code}.parquet"
                    df_factor.to_parquet(factor_path, index=False)

                updated += 1
                consecutive_fail = 0

                if updated % 50 == 0:
                    elapsed = time.time() - start_time
                    logger.info(
                        f"进度: {i + 1}/{total} | 更新={updated} 跳过={skipped} 失败={failed} | "
                        f"{elapsed:.0f}s"
                    )

            except Exception as e:
                failed += 1
                consecutive_fail += 1
                failed_codes.append(code)
                logger.warning(f"  {code} 失败: {e}")

    except KeyboardInterrupt:
        logger.info("手动中断")
    finally:
        bs.logout()
        elapsed = time.time() - start_time
        logger.info(f"\n===== 增量更新统计 =====")
        logger.info(f"更新: {updated} | 跳过: {skipped} | 失败: {failed}")
        logger.info(f"耗时: {elapsed:.1f}s")

        if failed_codes:
            failed_file = DATA_DIR / "logs" / "update_kline_failed.txt"
            with open(failed_file, "w") as f:
                f.write("\n".join(failed_codes))
            logger.info(f"失败列表: {failed_file} ({len(failed_codes)} 只)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--end-date", type=str, default=None, help="更新到哪天，默认今天"
    )
    args = parser.parse_args()
    main(end_date=args.end_date)
