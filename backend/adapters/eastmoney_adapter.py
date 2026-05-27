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
from backend.models.business_review import BusinessReviewRecord
from backend.models.event import DividendRecord
from backend.models.holder import (
    Top10HolderRecord,
    Top10FreeHolderRecord,
    HolderCountRecord,
)
from backend.models.management import ExecutiveRecord, ExecutiveHoldChangeRecord
from backend.models.pledge import PledgeRecord

logger = logging.getLogger(__name__)

BASE_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
EMWEB_BASE = "https://emweb.eastmoney.com/PC_HSF10"
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
    report_name: str,
    code: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort_column: str = "REPORT_DATE",
) -> List[dict]:
    """通用东方财富报表获取。

    sort_column:F10 不同接口的排序字段不同 — 财务三表用默认 REPORT_DATE,
    §7 控股股东三表(spike 验证)需 END_DATE。
    """
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
            "sortColumns": sort_column,
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


def _to_int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _gglb_to_executives(items: list) -> List[ExecutiveRecord]:
    """emweb gglb 字段 → ExecutiveRecord 列表。"""
    out: List[ExecutiveRecord] = []
    for it in items:
        name = (it.get("PERSON_NAME") or "").strip()
        if not name:
            continue
        try:
            out.append(
                ExecutiveRecord(
                    name=name,
                    position=it.get("POSITION"),
                    age=_to_int_or_none(it.get("AGE")),
                    sex=it.get("SEX"),
                    education=it.get("HIGH_DEGREE"),
                    tenure_text=it.get("INCUMBENT_TIME"),
                    resume=it.get("RESUME"),
                    hold_num=_to_float_or_none(it.get("HOLD_NUM")),
                    salary=_to_float_or_none(it.get("SALARY")),
                    source="eastmoney",
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"gglb 解析跳过 {name}: {e}")
    return out


def _cgbd_to_hold_changes(items: list) -> List[ExecutiveHoldChangeRecord]:
    """emweb cgbd → ExecutiveHoldChangeRecord 列表(按 END_DATE 降序保持原序)。"""
    out: List[ExecutiveHoldChangeRecord] = []
    for it in items:
        end_date_raw = it.get("END_DATE") or ""
        # END_DATE 形如 "2018-09-26 00:00:00"
        end_date = end_date_raw[:10] if len(end_date_raw) >= 10 else end_date_raw
        exec_name = (it.get("EXECUTIVE_NAME") or "").strip()
        change_num = _to_float_or_none(it.get("CHANGE_NUM"))
        if not end_date or not exec_name or change_num is None:
            continue
        try:
            out.append(
                ExecutiveHoldChangeRecord(
                    end_date=end_date,
                    executive_name=exec_name,
                    position=it.get("POSITION"),
                    change_num=change_num,
                    average_price=_to_float_or_none(it.get("AVERAGE_PRICE")),
                    change_after_holdnum=_to_float_or_none(
                        it.get("CHANGE_AFTER_HOLDNUM")
                    ),
                    trade_way=it.get("TRADE_WAY"),
                    executive_relation=it.get("EXECUTIVE_RELATION"),
                    source="eastmoney",
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"cgbd 解析跳过 {exec_name} {end_date}: {e}")
    return out


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

    # ---------- §7 控股股东 ----------
    # spike 验证(2026-05-24):F10 接口 sortColumns 必须用 END_DATE
    def fetch_top10_holders(self, code: str) -> List[Top10HolderRecord]:
        """十大股东(全部口径,含 H 股 / 限售)。"""
        records = _fetch_report("RPT_F10_EH_HOLDERS", code, sort_column="END_DATE")
        return _records_to_models(records, Top10HolderRecord)

    def fetch_top10_free_holders(self, code: str) -> List[Top10FreeHolderRecord]:
        """十大流通股东。"""
        records = _fetch_report("RPT_F10_EH_FREEHOLDERS", code, sort_column="END_DATE")
        return _records_to_models(records, Top10FreeHolderRecord)

    def fetch_holder_count_history(self, code: str) -> List[HolderCountRecord]:
        """股东户数(latest 接口,单期 + PRE_END_DATE 上期对比)。

        注:RPT_HOLDERNUMLATEST 每次只返回最近一期(count=1),长期趋势需周期性
        调用 + holder_repo.append 累积。
        """
        records = _fetch_report("RPT_HOLDERNUMLATEST", code, sort_column="END_DATE")
        return _records_to_models(records, HolderCountRecord)

    # ---------- D4 管理层(emweb F10 PageAjax) ----------
    # 2026-05-26 spike 验证(600519/002594):
    # GET https://emweb.eastmoney.com/PC_HSF10/CompanyManagement/PageAjax?code=SH600519
    # 返 {gglb: [...], cgbd: [...]} —— A 股专用,HK/US 不支持
    def fetch_company_management(
        self, code: str
    ) -> tuple[List[ExecutiveRecord], List[ExecutiveHoldChangeRecord]]:
        """高管列表 + 持股变动(A 股专用,HK/US 调用方应走 yfinance)。

        返回 (executives, hold_changes)。失败/空返 ([], [])。
        """
        if "." not in code:
            logger.debug(f"D4 EastMoney 跳过非标准 code={code}")
            return [], []

        sec, suffix = code.split(".")
        suffix = suffix.upper()
        if suffix not in ("SH", "SZ", "BJ"):
            logger.debug(f"D4 EastMoney 仅支持 A 股,跳过 {code}")
            return [], []

        em_code = f"{suffix}{sec}"
        url = f"{EMWEB_BASE}/CompanyManagement/PageAjax"
        try:
            resp = requests.get(url, params={"code": em_code}, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"D4 emweb CompanyManagement 失败 {code}: {exc}")
            return [], []

        if not isinstance(data, dict):
            return [], []

        executives = _gglb_to_executives(data.get("gglb") or [])
        hold_changes = _cgbd_to_hold_changes(data.get("cgbd") or [])
        return executives, hold_changes

    # ---------- §17.8 D&A 折旧摊销明细(GCASHFLOW) ----------
    # 2026-05-26 spike 验证(600519/2024):RPT_F10_FINANCE_GCASHFLOW 提供
    # FA_IR_DEPR + IA_AMORTIZE + LPE_AMORTIZE + USERIGHT_ASSET_AMORTIZE +
    # DEFER_INCOME_AMORTIZE 五项,合并即 D&A,可推导真实 EBITDA。
    # RPT_DMSK_FN_CASHFLOW(主缓存表)无此字段,故走单独接口实时拉。
    DA_FIELDS = (
        "FA_IR_DEPR",
        "IA_AMORTIZE",
        "LPE_AMORTIZE",
        "USERIGHT_ASSET_AMORTIZE",
        "DEFER_INCOME_AMORTIZE",
    )

    def fetch_da_breakdown(self, code: str, report_date: str) -> dict | None:
        """取指定 report_date(YYYY-MM-DD)的 D&A 五项明细。

        失败 / 非 A 股 / 该期无数据 → None。
        返回 dict 仅含 DA_FIELDS 五个键(None 占位 → 0 由调用方决定)+ REPORT_DATE。
        """
        if "." not in code:
            return None
        suffix = code.split(".")[1].upper()
        if suffix not in ("SH", "SZ", "BJ"):
            return None
        security_code = code.split(".")[0]
        params = {
            "reportName": "RPT_F10_FINANCE_GCASHFLOW",
            "columns": "ALL",
            "filter": (
                f"(SECURITY_CODE=\"{security_code}\")(REPORT_DATE='{report_date}')"
            ),
            "pageNumber": 1,
            "pageSize": 1,
            "source": "HSF10",
            "client": "PC",
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=DEFAULT_TIMEOUT)
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"D&A GCASHFLOW 失败 {code} {report_date}: {exc}")
            return None
        if not data.get("success") or not data.get("result"):
            return None
        rows = data["result"].get("data") or []
        if not rows:
            return None
        row = rows[0]
        out = {"REPORT_DATE": row.get("REPORT_DATE", report_date)[:10]}
        for k in self.DA_FIELDS:
            out[k] = _to_float_or_none(row.get(k))
        return out

    # ---------- §7 股权质押(中证登周频) ----------
    # 2026-05-26 spike 验证(600519):RPT_CSDC_LIST 返 weekly snapshots,
    # A 股全样本(2014 至今 ~586 条茅台)。字段:TRADE_DATE / PLEDGE_RATIO /
    # REPURCHASE_BALANCE / PLEDGE_DEAL_NUM / REPURCHASE_{LIMITED,UNLIMITED}_BALANCE /
    # PLEDGE_MARKET_CAP。HK / US 不支持。
    def fetch_pledge_history(self, code: str) -> List[PledgeRecord]:
        """股权质押周频快照(按 TRADE_DATE 降序)。失败 / 非 A 股 → []。"""
        if "." not in code:
            logger.debug(f"股权质押 跳过非标准 code={code}")
            return []
        suffix = code.split(".")[1].upper()
        if suffix not in ("SH", "SZ", "BJ"):
            logger.debug(f"股权质押 仅支持 A 股,跳过 {code}")
            return []
        records = _fetch_report("RPT_CSDC_LIST", code, sort_column="TRADE_DATE")
        return _records_to_models(records, PledgeRecord)

    # ---------- D5 经营评述(MD&A 全文) ----------
    # 2026-05-26 spike 验证(603939):RPT_F10_OP_BUSINESSANALYSIS 一次返回所有期
    # (年报/中报/季报),BUSINESS_REVIEW 为已结构化纯文本(年报 1.4-3.3k 字)。
    def fetch_business_review(self, code: str) -> List[BusinessReviewRecord]:
        """所有历史经营评述(按 REPORT_DATE 降序)。"""
        records = _fetch_report("RPT_F10_OP_BUSINESSANALYSIS", code)
        return _records_to_models(records, BusinessReviewRecord)

    def login(self):
        """兼容 BaoStockAdapter 接口,EastMoney 无需登录。"""
        pass

    def logout(self):
        pass
