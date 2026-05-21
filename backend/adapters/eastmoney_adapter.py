import logging
import time
from typing import List

import requests
import pandas as pd

from backend.adapters.base import FinancialDataAdapter, EventDataAdapter
from backend.models.financial import (
    IncomeStatement,
    BalanceSheet,
    CashFlow,
    FinancialIndicator,
)
from backend.models.event import DividendRecord

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


def _em_dividend_to_record(code: str, em: dict) -> DividendRecord | None:
    """EastMoney RPT_SHAREBONUS_DET 单条 → DividendRecord(BaoStock-style schema)。

    过滤规则:
    - EX_DIVIDEND_DATE 必须非空(预披露/不分配/未实施 → 跳过)
    - ASSIGN_PROGRESS 必须包含 "实施"(股东大会通过但未实施的也跳过)

    字段映射(EastMoney 单位:每 10 股 → 每股):
    - EX_DIVIDEND_DATE → dividOperateDate
    - PRETAX_BONUS_RMB / 10 → dividCashPsBeforeTax
    - BONUS_RATIO / 10 → dividStocksPs
    - IT_RATIO / 10 → dividReserveToStockPs
    - EQUITY_RECORD_DATE → dividRegistDate
    - PLAN_NOTICE_DATE → dividPlanAnnounceDate
    """
    ex_date = em.get("EX_DIVIDEND_DATE")
    if not ex_date:
        return None
    progress = em.get("ASSIGN_PROGRESS") or ""
    if "实施" not in progress:
        return None

    pretax = em.get("PRETAX_BONUS_RMB")
    bonus = em.get("BONUS_RATIO")
    it = em.get("IT_RATIO")

    data = {
        "code": code,
        "dividOperateDate": ex_date[:10],
        "dividCashPsBeforeTax": (pretax / 10.0) if pretax is not None else None,
        "dividStocksPs": (bonus / 10.0) if bonus is not None else None,
        "dividReserveToStockPs": (it / 10.0) if it is not None else None,
    }
    rec = em.get("EQUITY_RECORD_DATE")
    if rec:
        data["dividRegistDate"] = rec[:10]
    plan = em.get("PLAN_NOTICE_DATE")
    if plan:
        data["dividPlanAnnounceDate"] = plan[:10]
    notice = em.get("NOTICE_DATE")
    if notice:
        data["dividPlanDate"] = notice[:10]

    try:
        return DividendRecord(**data)
    except Exception as e:
        logger.debug(f"dividend record skip {code} {ex_date}: {e}")
        return None


class EastMoneyAdapter(FinancialDataAdapter, EventDataAdapter):
    """东方财富直接API适配器 — 财务数据 + 分红事件"""

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

    def fetch_dividends(self, code: str, year=None) -> List[DividendRecord]:
        """一次性返回该股所有历史分红(EastMoney 单接口,无需按年循环)。

        year 参数仅为兼容 BaoStockAdapter 签名,实际忽略。
        """
        records = _fetch_report("RPT_SHAREBONUS_DET", code)
        out = []
        for em in records:
            rec = _em_dividend_to_record(code, em)
            if rec is not None:
                out.append(rec)
        return out

    def login(self):
        """兼容 BaoStockAdapter 接口,EastMoney 无需登录。"""
        pass

    def logout(self):
        pass
