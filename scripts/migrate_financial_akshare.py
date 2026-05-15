"""
Phase 5 迁移脚本 — AKShare 财务数据获取（利润表/资产负债表/现金流量表/财务指标）

用法:
    # 全量获取
    python scripts/migrate_financial_akshare.py --migrate

    # 指定股票
    python scripts/migrate_financial_akshare.py --migrate --codes 000001.SZ 600000.SH
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters.akshare_adapter import AKShareAdapter
from backend.repositories.financial_repo import FinancialRepository
from backend.config import RAW_KLINE_DIR, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NEW_FINANCIAL_DIR = DATA_DIR / "financial" / "A_new"


def get_all_stock_codes() -> list:
    files = sorted(RAW_KLINE_DIR.glob("*.parquet"))
    return [f.stem for f in files if f.stem]


def migrate_financial(codes: list = None):
    """获取 AKShare 财务数据写入新目录"""
    NEW_FINANCIAL_DIR.mkdir(parents=True, exist_ok=True)

    if codes is None:
        codes = get_all_stock_codes()

    adapter = AKShareAdapter()
    repo = FinancialRepository(NEW_FINANCIAL_DIR)

    total = len(codes)
    success = {"income": 0, "balance": 0, "cashflow": 0, "indicator": 0}
    fail_count = 0

    for i, code in enumerate(codes):
        if (i + 1) % 50 == 0 or i == 0:
            logger.info(f"进度: {i + 1}/{total}")

        try:
            income = adapter.fetch_income(code)
            if income:
                repo.write_income(code, income)
                success["income"] += 1
        except Exception as e:
            logger.debug(f"  {code} income 失败: {e}")

        try:
            balance = adapter.fetch_balance(code)
            if balance:
                repo.write_balance(code, balance)
                success["balance"] += 1
        except Exception as e:
            logger.debug(f"  {code} balance 失败: {e}")

        try:
            cashflow = adapter.fetch_cashflow(code)
            if cashflow:
                repo.write_cashflow(code, cashflow)
                success["cashflow"] += 1
        except Exception as e:
            logger.debug(f"  {code} cashflow 失败: {e}")

        try:
            indicator = adapter.fetch_indicator(code)
            if indicator:
                repo.write_indicator(code, indicator)
                success["indicator"] += 1
        except Exception as e:
            logger.debug(f"  {code} indicator 失败: {e}")

        time.sleep(0.5)

    logger.info(f"\n===== 财务数据迁移完成 =====")
    logger.info(f"总股票数: {total}")
    for key, count in success.items():
        logger.info(f"  {key}: {count}/{total}")
    logger.info(f"数据目录: {NEW_FINANCIAL_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AKShare 财务数据迁移")
    parser.add_argument("--migrate", action="store_true", help="全量迁移模式")
    parser.add_argument("--codes", nargs="+", help="指定股票代码")
    args = parser.parse_args()

    if args.migrate:
        migrate_financial(codes=args.codes)
    else:
        parser.print_help()
