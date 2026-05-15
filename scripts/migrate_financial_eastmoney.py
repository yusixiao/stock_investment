"""
批量迁移东方财富财务数据（利润表/资产负债表/现金流量表/财务指标）

用法:
    python scripts/migrate_financial_eastmoney.py
    python scripts/migrate_financial_eastmoney.py --offset 100
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import RAW_KLINE_DIR, DATA_DIR
from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.repositories.financial_repo import FinancialRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "logs" / "migrate_financial.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

FINANCIAL_DIR = DATA_DIR / "market" / "A" / "financial"


def main(offset: int = 0):
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

    adapter = EastMoneyAdapter()
    repo = FinancialRepository(FINANCIAL_DIR)

    codes = sorted([f.stem for f in RAW_KLINE_DIR.glob("*.parquet") if f.stem])
    total = len(codes)
    codes = codes[offset:]

    logger.info(f"总股票数: {total}, 从 offset={offset} 开始, 剩余 {len(codes)} 只")

    success = 0
    fail = 0
    skipped = 0
    start_time = time.time()

    indicator_dir = FINANCIAL_DIR / "indicator"

    for i, code in enumerate(codes):
        idx = offset + i

        if (idx + 1) % 50 == 0:
            elapsed = time.time() - start_time
            speed = (i + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"进度: {idx + 1}/{total} | 成功={success} 跳过={skipped} 失败={fail} | {speed:.0f} 只/小时"
            )

        check_path = indicator_dir / f"{code}.parquet"
        if check_path.exists():
            skipped += 1
            continue

        try:
            income = adapter.fetch_income(code)
            balance = adapter.fetch_balance(code)
            cashflow = adapter.fetch_cashflow(code)
            indicator = adapter.fetch_indicator(code)

            if income:
                repo.write_income(code, income)
            if balance:
                repo.write_balance(code, balance)
            if cashflow:
                repo.write_cashflow(code, cashflow)
            if indicator:
                repo.write_indicator(code, indicator)

            if any([income, balance, cashflow, indicator]):
                success += 1
            else:
                skipped += 1

        except Exception as e:
            fail += 1
            if fail <= 20:
                logger.warning(f"  {code} 失败: {e}")

        time.sleep(0.15)

    elapsed = time.time() - start_time
    logger.info(f"\n===== 财务数据迁移统计 =====")
    logger.info(f"成功: {success} | 跳过: {skipped} | 失败: {fail}")
    logger.info(f"耗时: {elapsed / 60:.1f} 分钟")
    logger.info(
        f"断点续传: python scripts/migrate_financial_eastmoney.py --offset {idx + 1}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    main(offset=args.offset)
