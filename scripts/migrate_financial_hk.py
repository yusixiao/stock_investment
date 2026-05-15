"""
批量迁移港股财务数据（东方财富）

用法:
    python scripts/migrate_financial_hk.py
    python scripts/migrate_financial_hk.py --offset 100
    python scripts/migrate_financial_hk.py --codes 00700.HK,01810.HK
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATA_DIR

HK_FINANCIAL_DIR = DATA_DIR / "market" / "HK" / "financial"
STOCK_LIST_PATH = DATA_DIR / "market" / "HK" / "stock_list.csv"
LOG_PATH = DATA_DIR / "logs" / "migrate_financial_hk.log"

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

# ===== 港股科目 -> Core Data Model 字段映射 =====

INCOME_MAPPING = {
    "营业额": "OPERATE_INCOME",
    "营运收入": "OPERATE_INCOME",
    "营运支出": "OPERATE_EXPENSE",
    "毛利": "GROSS_PROFIT",
    "经营溢利": "OPERATE_PROFIT",
    "除税前溢利": "TOTAL_PROFIT",
    "税项": "INCOME_TAX",
    "除税后溢利": "NETPROFIT",
    "年度溢利": "NETPROFIT",
    "持续经营业务税后利润": "NETPROFIT",
    "本公司拥有人应占溢利": "PARENT_NETPROFIT",
    "股东应占溢利": "PARENT_NETPROFIT",
    "其他收益": "OTHER_INCOME",
    "销售及分销费用": "SELLING_EXPENSE",
    "行政开支": "ADMIN_EXPENSE",
    "融资成本": "FINANCE_EXPENSE",
    "利息收入": "INTEREST_INCOME",
    "应占联营公司溢利": "SHARE_OF_ASSOCIATES",
    "应占合营公司溢利": "SHARE_OF_ASSOCIATES",
    "每股基本盈利": "BASIC_EPS",
}

BALANCE_MAPPING = {
    "总资产": "TOTAL_ASSETS",
    "总负债": "TOTAL_LIABILITIES",
    "净资产": "TOTAL_EQUITY",
    "总权益": "TOTAL_EQUITY",
    "股东权益": "TOTAL_PARENT_EQUITY",
    "股本": "SHARE_CAPITAL",
    "股本溢价": "CAPITAL_RESERVE",
    "保留溢利(累计亏损)": "RETAINED_PROFITS",
    "其他储备": "SURPLUS_RESERVE",
    "库存股": "TREASURY_SHARES",
    "应收帐款": "ACCOUNTS_RECE",
    "无形资产": "INTANGIBLE_ASSET",
    "物业厂房及设备": "FIXED_ASSET",
    "非流动资产合计": "NON_CURRENT_ASSETS",
    "流动资产合计": "CURRENT_ASSETS",
    "流动负债合计": "CURRENT_LIABILITIES",
    "非流动负债合计": "NON_CURRENT_LIABILITIES",
    "净流动资产": "NET_CURRENT_ASSETS",
    "总资产减流动负债": "TOTAL_ASSETS_LESS_CL",
    "少数股东权益": "MINORITY_EQUITY",
    "存货": "INVENTORY",
    "现金及等价物": "CASH_EQUIVALENTS",
    "短期贷款": "SHORT_TERM_DEBT",
    "长期贷款": "LONG_TERM_DEBT",
    "总权益及总负债": "TOTAL_ASSETS",
}

CASHFLOW_MAPPING = {
    "经营业务现金净额": "NETCASH_OPERATE",
    "投资业务现金净额": "NETCASH_INVEST",
    "融资业务现金净额": "NETCASH_FINANCE",
    "现金净额": "CCE_ADD",
    "期初现金": "BEGIN_CCE",
    "期末现金": "END_CCE",
    "融资前现金净额": "CASH_BEFORE_FINANCING",
    "折旧及摊销": "DEPRECIATION_AMORTIZATION",
    "已付利息(融资)": "INTEREST_PAID",
    "已收利息(投资)": "INTEREST_RECEIVED",
    "已付股息(融资)": "DIVIDENDS_PAID",
    "购建固定资产": "CAPEX",
    "已付税项": "TAX_PAID",
    "新增借款": "NEW_BORROWINGS",
    "偿还借款": "REPAY_BORROWINGS",
    "回购股份": "SHARE_REPURCHASE",
}

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


def _fetch_with_timeout(func, *args, timeout=30, **kwargs):
    """带超时的函数调用"""
    import signal

    def _handler(signum, frame):
        raise TimeoutError("请求超时")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        result = func(*args, **kwargs)
        signal.alarm(0)
        return result
    except TimeoutError:
        raise
    finally:
        signal.signal(signal.SIGALRM, old)
        signal.alarm(0)


def _fetch_hk_report(stock: str, symbol: str, indicator: str = "年度") -> pd.DataFrame:
    """调用东方财富港股财报接口，带重试和超时"""
    import akshare as ak

    for attempt in range(3):
        try:
            df = _fetch_with_timeout(
                ak.stock_financial_hk_report_em,
                stock=stock,
                symbol=symbol,
                indicator=indicator,
                timeout=30,
            )
            return df
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
            else:
                raise e
    return pd.DataFrame()


def _fetch_hk_indicator(symbol: str, indicator: str = "年度") -> pd.DataFrame:
    """调用东方财富港股财务指标接口，带重试和超时"""
    import akshare as ak

    for attempt in range(3):
        try:
            df = _fetch_with_timeout(
                ak.stock_financial_hk_analysis_indicator_em,
                symbol=symbol,
                indicator=indicator,
                timeout=30,
            )
            return df
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
            else:
                raise e
    return pd.DataFrame()


def pivot_report(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """将纵向科目格式 pivot 成横向报告期格式，并应用字段映射"""
    if df.empty:
        return pd.DataFrame()

    df = df[["REPORT_DATE", "STD_ITEM_NAME", "AMOUNT"]].copy()
    df["REPORT_DATE"] = df["REPORT_DATE"].str[:10]

    pivoted = df.pivot_table(
        index="REPORT_DATE", columns="STD_ITEM_NAME", values="AMOUNT", aggfunc="first"
    ).reset_index()

    result = pd.DataFrame()
    result["REPORT_DATE"] = pivoted["REPORT_DATE"]

    for cn_name, eng_field in mapping.items():
        if cn_name in pivoted.columns:
            if eng_field not in result.columns:
                result[eng_field] = pivoted[cn_name]
            else:
                # 如果已有值但当前行为空，用新值填充
                mask = result[eng_field].isna()
                result.loc[mask, eng_field] = pivoted.loc[mask, cn_name]

    # 保留未映射的港股特有科目（用STD_ITEM_CODE格式命名）
    for col in pivoted.columns:
        if col != "REPORT_DATE" and col not in mapping:
            safe_name = f"HK_{col}"
            result[safe_name] = pivoted[col]

    result = result.sort_values("REPORT_DATE", ascending=False).reset_index(drop=True)
    return result


def transform_indicator(df: pd.DataFrame) -> pd.DataFrame:
    """将港股指标表的字段映射到 Core Data Model"""
    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame()
    result["REPORT_DATE"] = df["REPORT_DATE"].str[:10]

    for src_field, dst_field in INDICATOR_MAPPING.items():
        if src_field in df.columns:
            result[dst_field] = pd.to_numeric(df[src_field], errors="coerce")

    result = result.sort_values("REPORT_DATE", ascending=False).reset_index(drop=True)
    return result


def save_financial(code: str, table_name: str, df: pd.DataFrame):
    """保存财务数据为 parquet"""
    out_dir = HK_FINANCIAL_DIR / table_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code}.parquet"
    df.to_parquet(out_path, index=False)


def load_stock_list() -> list[str]:
    codes = []
    with open(STOCK_LIST_PATH) as f:
        next(f)
        for line in f:
            code = line.strip().split(",")[0]
            if code:
                codes.append(code)
    return codes


def migrate_one(code: str) -> dict:
    """迁移一只港股的财务数据，返回结果统计"""
    stock_num = code.replace(".HK", "")
    results = {}

    # 利润表
    try:
        df = _fetch_hk_report(stock_num, "利润表")
        if not df.empty:
            pivoted = pivot_report(df, INCOME_MAPPING)
            if not pivoted.empty:
                save_financial(code, "income", pivoted)
                results["income"] = len(pivoted)
    except Exception as e:
        results["income_err"] = str(e)

    time.sleep(0.5)

    # 资产负债表
    try:
        df = _fetch_hk_report(stock_num, "资产负债表")
        if not df.empty:
            pivoted = pivot_report(df, BALANCE_MAPPING)
            if not pivoted.empty:
                save_financial(code, "balance", pivoted)
                results["balance"] = len(pivoted)
    except Exception as e:
        results["balance_err"] = str(e)

    time.sleep(0.5)

    # 现金流量表
    try:
        df = _fetch_hk_report(stock_num, "现金流量表")
        if not df.empty:
            pivoted = pivot_report(df, CASHFLOW_MAPPING)
            if not pivoted.empty:
                save_financial(code, "cashflow", pivoted)
                results["cashflow"] = len(pivoted)
    except Exception as e:
        results["cashflow_err"] = str(e)

    time.sleep(0.5)

    # 财务指标
    try:
        df = _fetch_hk_indicator(stock_num)
        if not df.empty:
            transformed = transform_indicator(df)
            if not transformed.empty:
                save_financial(code, "indicator", transformed)
                results["indicator"] = len(transformed)
    except Exception as e:
        results["indicator_err"] = str(e)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--codes", type=str, default="")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    args = parser.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        codes = load_stock_list()

    total = len(codes)
    logger.info(f"港股财务迁移启动: 共 {total} 只, offset={args.offset}")

    success = 0
    empty = 0
    fail = 0
    skipped = 0
    start_time = time.time()

    for i, code in enumerate(codes[args.offset :], start=args.offset):
        if (i + 1) % 20 == 0:
            elapsed = time.time() - start_time
            speed = (i - args.offset + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"进度: [{i + 1}/{total}] 成功={success} 空={empty} 失败={fail} "
                f"跳过={skipped} | {speed:.0f} 只/小时"
            )

        if args.skip_existing:
            income_path = HK_FINANCIAL_DIR / "income" / f"{code}.parquet"
            if income_path.exists():
                skipped += 1
                continue

        try:
            results = migrate_one(code)
            has_data = any(
                k in results for k in ["income", "balance", "cashflow", "indicator"]
            )
            has_err = any("_err" in k for k in results)

            if has_data:
                success += 1
                tables = [
                    f"{k}={v}" for k, v in results.items() if not k.endswith("_err")
                ]
                logger.info(f"  [{i + 1}/{total}] {code} 完成: {', '.join(tables)}")
            elif has_err:
                fail += 1
                errs = [f"{k}={v}" for k, v in results.items() if k.endswith("_err")]
                logger.error(f"  [{i + 1}/{total}] {code} 失败: {'; '.join(errs)}")
            else:
                empty += 1

        except Exception as e:
            fail += 1
            logger.error(f"  [{i + 1}/{total}] {code} 异常: {e}")

        time.sleep(1)

    logger.info(
        f"迁移完成: 成功={success} 空={empty} 失败={fail} 跳过={skipped} / 总计={total}"
    )


if __name__ == "__main__":
    main()
