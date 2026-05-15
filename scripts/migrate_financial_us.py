"""
批量迁移美股财务数据（SEC EDGAR companyfacts API）

数据源: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
限速: 10次/秒，User-Agent 必填
过滤: form=10-K, fp=FY 取年报数据

用法:
    python scripts/migrate_financial_us.py
    python scripts/migrate_financial_us.py --offset 100
    python scripts/migrate_financial_us.py --codes AAPL,MSFT,GOOGL
    python scripts/migrate_financial_us.py --skip-existing
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATA_DIR
from backend.models.financial import (
    BalanceSheet,
    CashFlow,
    IncomeStatement,
    FinancialIndicator,
)
from backend.repositories.base import write_models_as_parquet

US_FINANCIAL_DIR = DATA_DIR / "market" / "US" / "financial"
STOCK_LIST_PATH = DATA_DIR / "market" / "US" / "stock_list.csv"
LOG_PATH = DATA_DIR / "logs" / "migrate_financial_us.log"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
for sub in ("income", "balance", "cashflow", "indicator"):
    (US_FINANCIAL_DIR / sub).mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

USER_AGENT = "StockInvestment admin@stockinvest.local"
BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# ===== SEC EDGAR us-gaap -> Core Data Model 映射 =====

INCOME_CONCEPTS = {
    "Revenues": "OPERATE_INCOME",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "OPERATE_INCOME",
    "SalesRevenueNet": "OPERATE_INCOME",
    "RevenueFromContractWithCustomerIncludingAssessedTax": "OPERATE_INCOME",
    "CostOfGoodsAndServicesSold": "COST_OF_REVENUE",
    "CostOfRevenue": "COST_OF_REVENUE",
    "GrossProfit": "GROSS_PROFIT",
    "OperatingIncomeLoss": "OPERATE_PROFIT",
    "OperatingExpenses": "OPERATE_EXPENSE",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "TOTAL_PROFIT",
    "IncomeTaxExpenseBenefit": "INCOME_TAX",
    "NetIncomeLoss": "NETPROFIT",
    "NetIncomeLossAvailableToCommonStockholdersBasic": "PARENT_NETPROFIT",
    "EarningsPerShareBasic": "BASIC_EPS",
    "ResearchAndDevelopmentExpense": "RESEARCH_EXPENSE",
    "SellingGeneralAndAdministrativeExpense": "SGA_EXPENSE",
    "InterestExpense": "INTEREST_EXPENSE",
    "InterestIncomeExpenseNet": "INTEREST_INCOME",
}

BALANCE_CONCEPTS = {
    "Assets": "TOTAL_ASSETS",
    "Liabilities": "TOTAL_LIABILITIES",
    "StockholdersEquity": "TOTAL_EQUITY",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "TOTAL_EQUITY",
    "CommonStockSharesOutstanding": "COMMON_STOCK_SHARES",
    "CashAndCashEquivalentsAtCarryingValue": "CASH_EQUIVALENTS",
    "AccountsReceivableNetCurrent": "ACCOUNTS_RECE",
    "Goodwill": "GOODWILL",
    "PropertyPlantAndEquipmentNet": "FIXED_ASSET",
    "LongTermDebt": "LONG_TERM_DEBT",
    "LongTermDebtNoncurrent": "LONG_TERM_DEBT",
    "ShortTermBorrowings": "SHORT_TERM_DEBT",
    "CommercialPaper": "SHORT_TERM_DEBT",
    "InventoryNet": "INVENTORY",
    "Inventory": "INVENTORY",
    "RetainedEarningsAccumulatedDeficit": "RETAINED_PROFITS",
    "IntangibleAssetsNetExcludingGoodwill": "INTANGIBLE_ASSET",
    "TreasuryStockValue": "TREASURY_SHARES",
    "MinorityInterest": "MINORITY_EQUITY",
    "AssetsCurrent": "CURRENT_ASSETS",
    "AssetsNoncurrent": "NON_CURRENT_ASSETS",
    "LiabilitiesCurrent": "CURRENT_LIABILITIES",
    "LiabilitiesNoncurrent": "NON_CURRENT_LIABILITIES",
    "CommonStockValue": "SHARE_CAPITAL",
    "AdditionalPaidInCapital": "CAPITAL_RESERVE",
    "AdditionalPaidInCapitalCommonStock": "CAPITAL_RESERVE",
}

CASHFLOW_CONCEPTS = {
    "NetCashProvidedByUsedInOperatingActivities": "NETCASH_OPERATE",
    "NetCashProvidedByUsedInInvestingActivities": "NETCASH_INVEST",
    "NetCashProvidedByUsedInFinancingActivities": "NETCASH_FINANCE",
    "DepreciationDepletionAndAmortization": "DEPRECIATION_AMORTIZATION",
    "DepreciationAndAmortization": "DEPRECIATION_AMORTIZATION",
    "PaymentsToAcquirePropertyPlantAndEquipment": "CAPEX",
    "PaymentsOfDividends": "DIVIDENDS_PAID",
    "PaymentsOfDividendsCommonStock": "DIVIDENDS_PAID",
    "PaymentsForRepurchaseOfCommonStock": "SHARE_REPURCHASE",
    "InterestPaidNet": "INTEREST_PAID",
    "InterestPaid": "INTEREST_PAID",
    "IncomeTaxesPaid": "TAX_PAID",
    "IncomeTaxesPaidNet": "TAX_PAID",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect": "CCE_ADD",
    "CashAndCashEquivalentsPeriodIncreaseDecrease": "CCE_ADD",
    "RepaymentsOfLongTermDebt": "REPAY_BORROWINGS",
    "ProceedsFromIssuanceOfLongTermDebt": "NEW_BORROWINGS",
}

# 优先级：当同一字段有多个候选科目时，越靠前越优先
INCOME_PRIORITY = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
BALANCE_EQUITY_PRIORITY = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]


def load_stock_list() -> list[tuple[str, str, str]]:
    """返回 [(ticker, cik, name), ...]"""
    results = []
    with open(STOCK_LIST_PATH) as f:
        next(f)
        for line in f:
            parts = line.strip().split(",", 2)
            if len(parts) >= 3:
                results.append((parts[0], parts[1], parts[2]))
            elif len(parts) == 2:
                results.append((parts[0], parts[1], ""))
    return results


def fetch_companyfacts(cik: str) -> Optional[dict]:
    """从 SEC EDGAR 获取 companyfacts JSON"""
    cik_padded = cik.lstrip("0").zfill(10)
    url = BASE_URL.format(cik=cik_padded)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        if e.code == 404:
            return None
        logger.warning(f"  HTTP {e.code} for CIK {cik}")
        return None
    except (URLError, TimeoutError) as e:
        logger.warning(f"  网络错误 CIK {cik}: {e}")
        return None


def extract_annual_values(
    facts: dict, concept: str, is_instant: bool = False
) -> dict[str, float]:
    """从 companyfacts 提取年报数据，返回 {end_date: value}

    is_instant: 资产负债表科目为瞬时值（无 start），不需要期间过滤
    流量科目(利润表/现金流)需过滤期间 >= 300天，排除季度分段数据
    """
    from datetime import date as dt_date

    if concept not in facts:
        return {}

    units = facts[concept].get("units", {})
    entries = []
    for unit_key, unit_entries in units.items():
        entries.extend(unit_entries)

    result = {}
    for entry in entries:
        if entry.get("form") != "10-K":
            continue
        if entry.get("fp") != "FY":
            continue
        end_date = entry.get("end")
        if not end_date:
            continue
        val = entry.get("val")
        if val is None:
            continue

        if not is_instant:
            start_date = entry.get("start")
            if start_date:
                try:
                    s = dt_date.fromisoformat(start_date)
                    e = dt_date.fromisoformat(end_date)
                    if (e - s).days < 300:
                        continue
                except ValueError:
                    pass

        if end_date not in result:
            result[end_date] = float(val)

    return result


def build_statements(
    facts: dict,
    concept_mapping: dict,
    priority_groups: list[list[str]] = None,
    is_instant: bool = False,
) -> dict[str, dict[str, float]]:
    """
    构建 {field_name: {report_date: value}} 字典
    priority_groups: 对于同一目标字段有多个候选科目时，按优先级取第一个有数据的
    is_instant: 资产负债表为瞬时值
    """
    field_data: dict[str, dict[str, float]] = {}

    handled_fields = set()
    if priority_groups:
        for group in priority_groups:
            target_field = None
            for concept in group:
                if concept in concept_mapping:
                    target_field = concept_mapping[concept]
                    break
            if not target_field:
                continue

            for concept in reversed(group):
                if concept not in concept_mapping:
                    continue
                values = extract_annual_values(facts, concept, is_instant=is_instant)
                if values:
                    if target_field not in field_data:
                        field_data[target_field] = {}
                    for date, val in values.items():
                        field_data[target_field][date] = val
            if target_field in field_data:
                handled_fields.add(target_field)

    for concept, field in concept_mapping.items():
        if field in handled_fields:
            continue
        values = extract_annual_values(facts, concept, is_instant=is_instant)
        if values:
            if field not in field_data:
                field_data[field] = values
            else:
                for date, val in values.items():
                    if date not in field_data[field]:
                        field_data[field][date] = val

    return field_data


def field_data_to_records(field_data: dict[str, dict[str, float]], model_class):
    """将 {field: {date: val}} 转为按 report_date 聚合的模型列表"""
    all_dates = set()
    for date_vals in field_data.values():
        all_dates.update(date_vals.keys())

    if not all_dates:
        return []

    records = []
    for date in sorted(all_dates):
        data = {"REPORT_DATE": date, "REPORT_TYPE": "10-K"}
        for field, date_vals in field_data.items():
            if date in date_vals:
                data[field] = date_vals[date]
        records.append(model_class(**data))

    return records


def compute_indicators(
    income_records: list[IncomeStatement],
    balance_records: list[BalanceSheet],
    facts: dict = None,
) -> list[FinancialIndicator]:
    """从利润表+资产负债表计算财务指标"""
    indicators = []

    diluted_eps_by_date = {}
    if facts:
        diluted_eps_by_date = extract_annual_values(facts, "EarningsPerShareDiluted")

    income_by_date = {r.REPORT_DATE: r for r in income_records}
    balance_by_date = {r.REPORT_DATE: r for r in balance_records}
    sorted_dates = sorted(income_by_date.keys())

    for i, date in enumerate(sorted_dates):
        inc = income_by_date[date]
        bal = balance_by_date.get(date)

        data = {"REPORT_DATE": date, "REPORT_TYPE": "10-K"}

        if inc.BASIC_EPS is not None:
            data["EPSJB"] = inc.BASIC_EPS
        if date in diluted_eps_by_date:
            data["DILUTED_EPS"] = diluted_eps_by_date[date]

        if bal:
            if bal.TOTAL_ASSETS and bal.TOTAL_LIABILITIES:
                data["ZCFZL"] = bal.TOTAL_LIABILITIES / bal.TOTAL_ASSETS * 100
            if bal.TOTAL_EQUITY and bal.COMMON_STOCK_SHARES:
                data["BPS"] = bal.TOTAL_EQUITY / bal.COMMON_STOCK_SHARES
            if inc.NETPROFIT and bal.TOTAL_EQUITY and bal.TOTAL_EQUITY != 0:
                data["ROEJQ"] = inc.NETPROFIT / bal.TOTAL_EQUITY * 100
            if inc.NETPROFIT and bal.TOTAL_ASSETS and bal.TOTAL_ASSETS != 0:
                data["ROA"] = inc.NETPROFIT / bal.TOTAL_ASSETS * 100

        if inc.OPERATE_INCOME and inc.OPERATE_INCOME != 0:
            if inc.GROSS_PROFIT is not None:
                data["XSMLL"] = inc.GROSS_PROFIT / inc.OPERATE_INCOME * 100
                data["GROSS_PROFIT_RATIO"] = data["XSMLL"]
            if inc.NETPROFIT is not None:
                data["XSJLL"] = inc.NETPROFIT / inc.OPERATE_INCOME * 100
                data["NET_PROFIT_RATIO"] = data["XSJLL"]

        if i > 0:
            prev_date = sorted_dates[i - 1]
            prev_inc = income_by_date[prev_date]
            if (
                prev_inc.OPERATE_INCOME
                and prev_inc.OPERATE_INCOME != 0
                and inc.OPERATE_INCOME
            ):
                data["OPERATE_INCOME_YOY"] = (
                    (inc.OPERATE_INCOME - prev_inc.OPERATE_INCOME)
                    / abs(prev_inc.OPERATE_INCOME)
                    * 100
                )
                data["REVENUE_YOY"] = data["OPERATE_INCOME_YOY"]
            if prev_inc.NETPROFIT and prev_inc.NETPROFIT != 0 and inc.NETPROFIT:
                data["NETPROFIT_YOY"] = (
                    (inc.NETPROFIT - prev_inc.NETPROFIT) / abs(prev_inc.NETPROFIT) * 100
                )

        indicators.append(FinancialIndicator(**data))

    return indicators


def process_ticker(ticker: str, cik: str) -> dict[str, int]:
    """处理单只股票，返回各表记录数"""
    data = fetch_companyfacts(cik)
    if not data:
        return {}

    facts = data.get("facts", {}).get("us-gaap", {})
    if not facts:
        return {}

    income_priority = [[c for c in INCOME_PRIORITY if c in INCOME_CONCEPTS]]
    income_fields = build_statements(facts, INCOME_CONCEPTS, income_priority)
    income_records = field_data_to_records(income_fields, IncomeStatement)

    balance_priority = [[c for c in BALANCE_EQUITY_PRIORITY if c in BALANCE_CONCEPTS]]
    balance_fields = build_statements(
        facts, BALANCE_CONCEPTS, balance_priority, is_instant=True
    )
    balance_records = field_data_to_records(balance_fields, BalanceSheet)

    cashflow_fields = build_statements(facts, CASHFLOW_CONCEPTS)
    cashflow_records = field_data_to_records(cashflow_fields, CashFlow)

    indicator_records = compute_indicators(income_records, balance_records, facts)

    counts = {}
    if income_records:
        path = US_FINANCIAL_DIR / "income" / f"{ticker}.parquet"
        write_models_as_parquet(
            path, income_records, sort_by="REPORT_DATE", ascending=False
        )
        counts["income"] = len(income_records)

    if balance_records:
        path = US_FINANCIAL_DIR / "balance" / f"{ticker}.parquet"
        write_models_as_parquet(
            path, balance_records, sort_by="REPORT_DATE", ascending=False
        )
        counts["balance"] = len(balance_records)

    if cashflow_records:
        path = US_FINANCIAL_DIR / "cashflow" / f"{ticker}.parquet"
        write_models_as_parquet(
            path, cashflow_records, sort_by="REPORT_DATE", ascending=False
        )
        counts["cashflow"] = len(cashflow_records)

    if indicator_records:
        path = US_FINANCIAL_DIR / "indicator" / f"{ticker}.parquet"
        write_models_as_parquet(
            path, indicator_records, sort_by="REPORT_DATE", ascending=False
        )
        counts["indicator"] = len(indicator_records)

    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--codes", type=str, default="")
    parser.add_argument("--skip-existing", action="store_true", default=False)
    args = parser.parse_args()

    if args.codes:
        stocks = [(c.strip(), "", "") for c in args.codes.split(",")]
        ticker_to_cik = {}
        all_stocks = load_stock_list()
        for t, c, n in all_stocks:
            ticker_to_cik[t] = c
        stocks = [(t, ticker_to_cik.get(t, ""), "") for t, _, _ in stocks]
    else:
        stocks = load_stock_list()

    total = len(stocks)
    logger.info(f"美股财务迁移启动: 共 {total} 只, offset={args.offset}")

    success = 0
    empty = 0
    fail = 0
    skipped = 0
    start_time = time.time()

    for i, (ticker, cik, name) in enumerate(stocks[args.offset :], start=args.offset):
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_time
            speed = (i - args.offset + 1) / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"进度: [{i + 1}/{total}] 成功={success} 空={empty} 失败={fail} "
                f"跳过={skipped} | {speed:.0f} 只/小时"
            )

        if args.skip_existing:
            income_path = US_FINANCIAL_DIR / "income" / f"{ticker}.parquet"
            if income_path.exists():
                skipped += 1
                continue

        if not cik:
            empty += 1
            continue

        try:
            counts = process_ticker(ticker, cik)
            if not counts:
                empty += 1
            else:
                success += 1
                if (i + 1) % 50 == 0 or i < args.offset + 10:
                    logger.info(
                        f"  [{i + 1}/{total}] {ticker} 完成: "
                        + ", ".join(f"{k}={v}" for k, v in counts.items())
                    )
        except Exception as e:
            fail += 1
            logger.error(f"  [{i + 1}/{total}] {ticker} 异常: {e}")

        time.sleep(0.1)

    elapsed = time.time() - start_time
    logger.info(
        f"迁移完成: 成功={success} 空={empty} 失败={fail} 跳过={skipped} / "
        f"总计={total} | 耗时 {elapsed / 60:.1f} 分钟"
    )


if __name__ == "__main__":
    main()
