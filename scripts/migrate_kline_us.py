"""
批量迁移美股 K线 + 复权因子（yfinance）

用法:
    python scripts/migrate_kline_us.py
    python scripts/migrate_kline_us.py --offset 100
    python scripts/migrate_kline_us.py --codes AAPL,MSFT,GOOGL
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATA_DIR
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.repositories.base import write_models_as_parquet

US_DAILY_DIR = DATA_DIR / "market" / "US" / "daily"
US_ADJUST_DIR = DATA_DIR / "market" / "US" / "adjust_factor"
STOCK_LIST_PATH = DATA_DIR / "market" / "US" / "stock_list.csv"
LOG_PATH = DATA_DIR / "logs" / "migrate_kline_us.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
US_DAILY_DIR.mkdir(parents=True, exist_ok=True)
US_ADJUST_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def load_stock_list() -> list[tuple[str, str]]:
    """返回 [(ticker, cik), ...]"""
    results = []
    with open(STOCK_LIST_PATH) as f:
        next(f)
        for line in f:
            parts = line.strip().split(",", 2)
            if len(parts) >= 2:
                results.append((parts[0], parts[1]))
    return results


def fetch_kline(ticker: str) -> list[DailyKlineRecord]:
    """获取全量历史不复权K线"""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="max", auto_adjust=False)
    except Exception as e:
        logger.error(f"  yfinance K线失败 {ticker}: {e}")
        return []

    if df.empty:
        return []

    records = []
    prev_close = None
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        volume = float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0
        close = float(row["Close"])
        data = {
            "date": date_str,
            "code": ticker,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": close,
            "volume": volume,
            "amount": 0.0,
        }
        if prev_close is not None:
            data["preclose"] = prev_close
            data["pctChg"] = (close - prev_close) / prev_close * 100
        prev_close = close
        records.append(DailyKlineRecord(**data))

    return records


def fetch_adjust_factor(ticker: str) -> list[AdjustFactorRecord]:
    """从 dividends + splits 计算前复权因子"""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="max", auto_adjust=False)
        divs = t.dividends
        splits = t.splits
    except Exception as e:
        logger.error(f"  yfinance 复权因子失败 {ticker}: {e}")
        return []

    if hist.empty:
        return []

    events = []

    for dt, amount in divs.items():
        if amount <= 0:
            continue
        mask = hist.index < dt
        if not mask.any():
            continue
        prev_close = float(hist.loc[mask].iloc[-1]["Close"])
        if prev_close <= 0:
            continue
        factor_change = (prev_close - amount) / prev_close
        if factor_change <= 0 or factor_change > 1:
            continue
        events.append((dt.strftime("%Y-%m-%d"), factor_change))

    for dt, ratio in splits.items():
        if ratio <= 0 or ratio == 1.0:
            continue
        events.append((dt.strftime("%Y-%m-%d"), 1.0 / ratio))

    if not events:
        return []

    events.sort(key=lambda x: x[0])

    n = len(events)
    fore_factors = [0.0] * n
    fore_factors[n - 1] = 1.0
    for i in range(n - 2, -1, -1):
        fore_factors[i] = fore_factors[i + 1] * events[i + 1][1]

    records = []
    for i, (date_str, _) in enumerate(events):
        records.append(
            AdjustFactorRecord(
                code=ticker,
                dividOperateDate=date_str,
                foreAdjustFactor=round(fore_factors[i], 6),
            )
        )

    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--codes", type=str, default="")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    args = parser.parse_args()

    if args.codes:
        stocks = [(c.strip(), "") for c in args.codes.split(",")]
    else:
        stocks = load_stock_list()

    total = len(stocks)
    logger.info(f"美股K线迁移启动: 共 {total} 只, offset={args.offset}")

    success = 0
    empty = 0
    fail = 0
    skipped = 0
    start_time = time.time()

    for i, (ticker, cik) in enumerate(stocks[args.offset :], start=args.offset):
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            speed = (i - args.offset + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"进度: [{i + 1}/{total}] 成功={success} 空={empty} 失败={fail} "
                f"跳过={skipped} | {speed:.0f} 只/小时"
            )

        daily_path = US_DAILY_DIR / f"{ticker}.parquet"
        if args.skip_existing and daily_path.exists():
            skipped += 1
            continue

        try:
            records = fetch_kline(ticker)
            if not records:
                empty += 1
                continue

            write_models_as_parquet(
                daily_path, records, sort_by="date", ascending=False
            )

            factors = fetch_adjust_factor(ticker)
            if factors:
                factor_path = US_ADJUST_DIR / f"{ticker}.parquet"
                write_models_as_parquet(
                    factor_path, factors, sort_by="dividOperateDate", ascending=True
                )

            success += 1
            if (i + 1) % 50 == 0 or i < args.offset + 10:
                logger.info(
                    f"  [{i + 1}/{total}] {ticker} 完成: {len(records)} 行K线, {len(factors)} 条因子"
                )

        except Exception as e:
            fail += 1
            logger.error(f"  [{i + 1}/{total}] {ticker} 异常: {e}")

        time.sleep(0.5)

    logger.info(
        f"迁移完成: 成功={success} 空={empty} 失败={fail} 跳过={skipped} / 总计={total}"
    )


if __name__ == "__main__":
    main()
