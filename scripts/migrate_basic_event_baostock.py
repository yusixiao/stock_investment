"""
Phase 5 迁移脚本 — BaoStock 基本信息 + 复权因子 + 分红数据

用法:
    python scripts/migrate_basic_event_baostock.py --migrate
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.baostock_adapter import BaoStockAdapter
from backend.repositories.basic_repo import BasicRepository
from backend.repositories.event_repo import EventRepository
from backend.repositories.market_repo import MarketRepository
from backend.config import RAW_KLINE_DIR, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NEW_BASIC_DIR = DATA_DIR / "basic" / "A"
NEW_EVENT_DIR = DATA_DIR / "event" / "A"
NEW_MARKET_DIR_DAILY = DATA_DIR / "market" / "A" / "daily"
NEW_MARKET_DIR_FACTOR = DATA_DIR / "market" / "A" / "adjust_factor"


def get_all_stock_codes() -> list:
    files = sorted(RAW_KLINE_DIR.glob("*.parquet"))
    return [f.stem for f in files if f.stem]


def migrate_basic():
    """获取全市场股票基本信息"""
    NEW_BASIC_DIR.mkdir(parents=True, exist_ok=True)
    adapter = BaoStockAdapter()
    repo = BasicRepository(NEW_BASIC_DIR)

    logger.info("获取全市场股票列表...")
    stocks = adapter.fetch_stock_list()
    if stocks:
        repo.write_stock_list(stocks)
        logger.info(f"股票列表写入成功: {len(stocks)} 只")
    else:
        logger.error("获取股票列表失败")


def migrate_dividends(codes: list = None):
    """获取分红数据"""
    NEW_EVENT_DIR.mkdir(parents=True, exist_ok=True)
    (NEW_EVENT_DIR / "dividend").mkdir(parents=True, exist_ok=True)

    if codes is None:
        codes = get_all_stock_codes()

    adapter = BaoStockAdapter()
    repo = EventRepository(NEW_EVENT_DIR)

    total = len(codes)
    success_count = 0

    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0 or i == 0:
            logger.info(f"分红数据进度: {i + 1}/{total}")

        try:
            divs = adapter.fetch_dividends(code)
            if divs:
                repo.write_dividends(code, divs)
                success_count += 1
        except Exception as e:
            logger.debug(f"  {code} 分红失败: {e}")

        time.sleep(0.05)

    logger.info(f"分红数据完成: {success_count}/{total}")


def migrate_adjust_factors(codes: list = None):
    """获取复权因子（如果 K线迁移脚本未同步获取）"""
    NEW_MARKET_DIR_FACTOR.mkdir(parents=True, exist_ok=True)

    if codes is None:
        codes = get_all_stock_codes()

    adapter = BaoStockAdapter()
    repo = MarketRepository(NEW_MARKET_DIR_DAILY, NEW_MARKET_DIR_FACTOR)

    total = len(codes)
    success_count = 0

    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0 or i == 0:
            logger.info(f"复权因子进度: {i + 1}/{total}")

        try:
            factors = adapter.fetch_adjust_factor(code)
            if factors:
                repo.write_adjust_factor(code, factors)
                success_count += 1
        except Exception as e:
            logger.debug(f"  {code} 复权因子失败: {e}")

        time.sleep(0.05)

    logger.info(f"复权因子完成: {success_count}/{total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BaoStock 基本信息/复权因子/分红迁移")
    parser.add_argument("--migrate", action="store_true", help="全量迁移")
    parser.add_argument("--basic-only", action="store_true", help="仅股票列表")
    parser.add_argument("--dividend-only", action="store_true", help="仅分红数据")
    parser.add_argument("--factor-only", action="store_true", help="仅复权因子")
    parser.add_argument("--codes", nargs="+", help="指定股票代码")
    args = parser.parse_args()

    if args.basic_only:
        migrate_basic()
    elif args.dividend_only:
        migrate_dividends(codes=args.codes)
    elif args.factor_only:
        migrate_adjust_factors(codes=args.codes)
    elif args.migrate:
        migrate_basic()
        migrate_adjust_factors(codes=args.codes)
        migrate_dividends(codes=args.codes)
    else:
        parser.print_help()
