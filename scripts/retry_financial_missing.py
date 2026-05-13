"""
补漏脚本：重新拉取财务数据中缺失的 balance/income/cashflow

扫描 indicator 目录（最全）与其他三个目录对比，找出缺失文件并重新拉取。
增加超时时间和重试机制。

用法:
    python scripts/retry_financial_missing.py
    python scripts/retry_financial_missing.py --timeout 30 --retries 3
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATA_DIR
from backend.adapters.eastmoney_adapter import EastMoneyAdapter
from backend.repositories.financial_repo import FinancialRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "logs" / "retry_financial.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

FINANCIAL_DIR = DATA_DIR / "market" / "A" / "financial"


def find_missing():
    indicator_codes = {f.stem for f in (FINANCIAL_DIR / "indicator").glob("*.parquet")}
    balance_codes = {f.stem for f in (FINANCIAL_DIR / "balance").glob("*.parquet")}
    income_codes = {f.stem for f in (FINANCIAL_DIR / "income").glob("*.parquet")}
    cashflow_codes = {f.stem for f in (FINANCIAL_DIR / "cashflow").glob("*.parquet")}

    missing = {}
    for code in sorted(indicator_codes):
        types = []
        if code not in balance_codes:
            types.append("balance")
        if code not in income_codes:
            types.append("income")
        if code not in cashflow_codes:
            types.append("cashflow")
        if types:
            missing[code] = types

    return missing


def main(timeout: int = 30, retries: int = 3):
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

    missing = find_missing()
    total = len(missing)
    logger.info(f"共发现 {total} 只股票有财务数据缺失")

    if total == 0:
        logger.info("无需补漏，全部完整")
        return

    import backend.adapters.eastmoney_adapter as em_mod

    em_mod.DEFAULT_TIMEOUT = timeout
    em_mod.MAX_RETRIES = retries

    adapter = EastMoneyAdapter()
    repo = FinancialRepository(FINANCIAL_DIR)

    success = 0
    still_failed = 0

    for i, (code, types) in enumerate(missing.items()):
        if (i + 1) % 20 == 0 or i == 0:
            logger.info(f"进度: {i + 1}/{total} | 成功={success} 失败={still_failed}")

        ok = True
        for t in types:
            fetched = False
            for attempt in range(1, retries + 1):
                try:
                    if t == "balance":
                        data = adapter.fetch_balance(code)
                        if data:
                            repo.write_balance(code, data)
                    elif t == "income":
                        data = adapter.fetch_income(code)
                        if data:
                            repo.write_income(code, data)
                    elif t == "cashflow":
                        data = adapter.fetch_cashflow(code)
                        if data:
                            repo.write_cashflow(code, data)
                    fetched = True
                    break
                except Exception as e:
                    if attempt == retries:
                        logger.warning(f"  {code} {t} 失败({retries}次): {e}")
                        ok = False
                    else:
                        time.sleep(2 * attempt)

            if not fetched and ok:
                ok = True

            time.sleep(0.3)

        if ok:
            success += 1
        else:
            still_failed += 1

    logger.info(f"\n===== 财务补漏统计 =====")
    logger.info(f"成功: {success} | 仍失败: {still_failed} / {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    main(timeout=args.timeout, retries=args.retries)
