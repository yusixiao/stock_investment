"""
补港股 indicator 数据 - 使用 pageSize=50 重新获取完整数据
"""

import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATA_DIR

HK_FINANCIAL_DIR = DATA_DIR / "market" / "HK" / "financial"
STOCK_LIST_PATH = DATA_DIR / "market" / "HK" / "stock_list.csv"
LOG_PATH = DATA_DIR / "logs" / "fix_hk_indicator.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

INDICATOR_MAPPING = {
    "BASIC_EPS": "EPSJB",
    "DILUTED_EPS": "DILUTED_EPS",
    "BPS": "BPS",
    "ROE_AVG": "ROEJQ",
    "GROSS_PROFIT_RATIO": "XSMLL",
    "NET_PROFIT_RATIO": "XSJLL",
    "DEBT_ASSET_RATIO": "ZCFZL",
    "CURRENT_RATIO": "LD",
    "ROA": "ROA",
    "ROIC_YEARLY": "ROIC",
    "OPERATE_INCOME_YOY": "OPERATE_INCOME_YOY",
    "GROSS_PROFIT_YOY": "GROSS_PROFIT_YOY",
    "HOLDER_PROFIT_YOY": "PARENT_NETPROFIT_YOY",
}


def fetch_indicator(symbol: str) -> pd.DataFrame:
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_HKF10_FN_MAININDICATOR",
        "columns": "HKF10_FN_MAININDICATOR",
        "quoteColumns": "",
        "pageNumber": "1",
        "pageSize": "50",
        "sortTypes": "-1",
        "sortColumns": "STD_REPORT_DATE",
        "source": "F10",
        "client": "PC",
        "filter": f'(SECUCODE="{symbol}.HK")(DATE_TYPE_CODE="001")',
    }
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            data = r.json()
            if data.get("result") and data["result"].get("data"):
                return pd.DataFrame(data["result"]["data"])
            return pd.DataFrame()
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
            else:
                raise e
    return pd.DataFrame()


def transform_indicator(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["REPORT_DATE"] = df["REPORT_DATE"].str[:10]

    for src_field, dst_field in INDICATOR_MAPPING.items():
        if src_field in df.columns:
            result[dst_field] = pd.to_numeric(df[src_field], errors="coerce")

    result = result.sort_values("REPORT_DATE", ascending=False).reset_index(drop=True)
    return result


def load_stock_list() -> list[str]:
    codes = []
    with open(STOCK_LIST_PATH) as f:
        next(f)
        for line in f:
            code = line.strip().split(",")[0]
            if code:
                codes.append(code)
    return codes


def main():
    codes = load_stock_list()
    total = len(codes)
    logger.info(f"港股 indicator 补数据启动: 共 {total} 只, pageSize=50")

    out_dir = HK_FINANCIAL_DIR / "indicator"
    out_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    empty = 0
    fail = 0
    start_time = time.time()

    for i, code in enumerate(codes):
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            speed = (i + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"进度: [{i + 1}/{total}] 成功={success} 空={empty} 失败={fail} | {speed:.0f} 只/小时"
            )

        stock_num = code.replace(".HK", "")
        try:
            df = fetch_indicator(stock_num)
            if not df.empty:
                transformed = transform_indicator(df)
                if not transformed.empty:
                    transformed.to_parquet(out_dir / f"{code}.parquet", index=False)
                    success += 1
                    if (i + 1) % 100 == 0:
                        logger.info(
                            f"  [{i + 1}/{total}] {code} 完成: {len(transformed)} 期"
                        )
                else:
                    empty += 1
            else:
                empty += 1
        except Exception as e:
            fail += 1
            logger.error(f"  [{i + 1}/{total}] {code} 失败: {e}")

        time.sleep(0.5)

    logger.info(f"完成: 成功={success} 空={empty} 失败={fail} / 总计={total}")


if __name__ == "__main__":
    main()
