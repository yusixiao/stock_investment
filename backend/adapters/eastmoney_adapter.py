import logging
import time
from typing import List

import requests
import pandas as pd

from backend.adapters.base import FinancialDataAdapter
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
DEFAULT_TIMEOUT = 15
DEFAULT_PAGE_SIZE = 200
REQUEST_INTERVAL = 0.1


MAX_RETRIES = 3
RETRY_BASE_DELAY = 2


def _fetch_page_with_retry(params: dict, code: str, report_name: str) -> dict | None:
    """单页请求 + 指数退避重试"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=DEFAULT_TIMEOUT)
            return resp.json()
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.debug(
                    f"重试 {code} {report_name} (第{attempt + 2}次, {delay}s后)"
                )
                time.sleep(delay)
            else:
                logger.error(f"东方财富API请求失败 {code} {report_name}: {e}")
                return None


def _fetch_report(
    report_name: str, code: str, page_size: int = DEFAULT_PAGE_SIZE
) -> List[dict]:
    """通用东方财富报表获取"""
    security_code = code.split(".")[0] if "." in code else code

    all_records = []
    page = 1

    while True:
        params = {
            "reportName": report_name,
            "columns": "ALL",
            "quoteColumns": "",
            "filter": f'(SECURITY_CODE="{security_code}")',
            "pageNumber": page,
            "pageSize": page_size,
            "sortTypes": -1,
            "sortColumns": "REPORT_DATE",
            "source": "HSF10",
            "client": "PC",
        }

        data = _fetch_page_with_retry(params, code, report_name)
        if data is None:
            return all_records

        if not data.get("success") or not data.get("result"):
            break

        result = data["result"]
        records = result.get("data", [])
        if not records:
            break

        all_records.extend(records)

        total_pages = result.get("pages", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)

    return all_records


def _clean_record(record: dict) -> dict:
    """清理记录：处理日期格式、移除None值"""
    cleaned = {}
    for k, v in record.items():
        if v is None:
            continue
        if isinstance(v, str) and len(v) >= 10 and v[4:5] == "-" and v[7:8] == "-":
            cleaned[k] = v[:10]
        else:
            cleaned[k] = v
    return cleaned


def _records_to_models(records: List[dict], model_class) -> list:
    """将API返回的dict列表转换为Pydantic模型"""
    if not records:
        return []

    models = []
    for record in records:
        cleaned = _clean_record(record)
        try:
            models.append(model_class(**cleaned))
        except Exception as e:
            logger.debug(f"模型解析跳过: {e}")
            continue
    return models


class EastMoneyAdapter(FinancialDataAdapter):
    """东方财富直接API适配器 — 替代AKShare获取财务数据"""

    def fetch_income(self, code: str) -> List[IncomeStatement]:
        records = _fetch_report("RPT_DMSK_FN_INCOME", code)
        return _records_to_models(records, IncomeStatement)

    def fetch_balance(self, code: str) -> List[BalanceSheet]:
        records = _fetch_report("RPT_DMSK_FN_BALANCE", code)
        return _records_to_models(records, BalanceSheet)

    def fetch_cashflow(self, code: str) -> List[CashFlow]:
        records = _fetch_report("RPT_DMSK_FN_CASHFLOW", code)
        return _records_to_models(records, CashFlow)

    def fetch_indicator(self, code: str) -> List[FinancialIndicator]:
        records = _fetch_report("RPT_F10_FINANCE_MAINFINADATA", code)
        return _records_to_models(records, FinancialIndicator)
