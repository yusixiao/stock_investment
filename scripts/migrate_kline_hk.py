"""
批量迁移港股 K线 + 复权因子（yfinance）

用法:
    python scripts/migrate_kline_hk.py
    python scripts/migrate_kline_hk.py --offset 100
    python scripts/migrate_kline_hk.py --codes 00700.HK,01810.HK
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.yfinance_adapter import YFinanceAdapter
from backend.config import DATA_DIR
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.repositories.base import write_models_as_parquet

HK_DAILY_DIR = DATA_DIR / "market" / "HK" / "daily"
HK_ADJUST_DIR = DATA_DIR / "market" / "HK" / "adjust_factor"
STOCK_LIST_PATH = DATA_DIR / "market" / "HK" / "stock_list.csv"
LOG_PATH = DATA_DIR / "logs" / "migrate_kline_hk.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
HK_DAILY_DIR.mkdir(parents=True, exist_ok=True)
HK_ADJUST_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def load_stock_list() -> list[str]:
    """从 stock_list.csv 读取港股代码列表"""
    codes = []
    with open(STOCK_LIST_PATH) as f:
        next(f)  # skip header
        for line in f:
            code = line.strip().split(",")[0]
            if code:
                codes.append(code)
    return codes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--codes", type=str, default="", help="逗号分隔的股票代码")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    args = parser.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        codes = load_stock_list()

    total = len(codes)
    logger.info(f"港股迁移启动: 共 {total} 只, offset={args.offset}")

    adapter = YFinanceAdapter()
    success = 0
    empty = 0
    fail = 0
    skipped = 0
    start_time = time.time()

    for i, code in enumerate(codes[args.offset :], start=args.offset):
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            speed = (i - args.offset + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"进度: [{i + 1}/{total}] 成功={success} 空={empty} 失败={fail} "
                f"跳过={skipped} | {speed:.0f} 只/小时"
            )

        daily_path = HK_DAILY_DIR / f"{code}.parquet"
        if args.skip_existing and daily_path.exists():
            skipped += 1
            continue

        try:
            records = adapter.fetch_daily_kline_full(code)
            if not records:
                empty += 1
                continue

            write_models_as_parquet(
                daily_path, records, sort_by="date", ascending=False
            )

            # 复权因子
            factors = adapter.fetch_adjust_factor(code)
            if factors:
                factor_path = HK_ADJUST_DIR / f"{code}.parquet"
                write_models_as_parquet(
                    factor_path, factors, sort_by="dividOperateDate", ascending=True
                )

            success += 1
            logger.info(
                f"  [{i + 1}/{total}] {code} 完成: {len(records)} 行K线, {len(factors)} 条因子"
            )

        except Exception as e:
            fail += 1
            logger.error(f"  [{i + 1}/{total}] {code} 失败: {e}")

        time.sleep(0.5)

    logger.info(
        f"迁移完成: 成功={success} 空={empty} 失败={fail} 跳过={skipped} / 总计={total}"
    )


if __name__ == "__main__":
    main()
