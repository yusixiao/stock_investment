import logging
import time
from typing import List

import requests
import pandas as pd

from backend.adapters.base import FinancialDataAdapter, EventDataAdapter, MarketDataAdapter
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
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

# A 股明细资产负债表按公司类型拆 4 张报表(spike 2026-07-02 验证 600519/601398/
# 600030/601318/002415):普通工商/银行/券商/保险,每张均含明细科目 GOODWILL /
# INTANGIBLE_ASSET / TOTAL_PARENT_EQUITY / MINORITY_EQUITY(简况 RPT_DMSK_FN_BALANCE
# 仅 57 列、缺这些科目)。每张报表仅返回对应公司类型的数据,其余返回空(success=False
# "返回数据为空")。按普通→银行→券商→保险顺序试,首个非空即用(普通型覆盖绝大多数,
# 命中率最高)。全空(极少数特殊主体)兜底回简况,保证聚合字段(总资产/负债/权益)不回归。
_BALANCE_DETAIL_REPORTS = (
    "RPT_F10_FINANCE_GBALANCE",  # 普通工商(319 列)
    "RPT_F10_FINANCE_BBALANCE",  # 银行(221 列)
    "RPT_F10_FINANCE_SBALANCE",  # 券商(215 列)
    "RPT_F10_FINANCE_IBALANCE",  # 保险(253 列)
)


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


def _fetch_industry_fields(code: str) -> dict:
    """补取行业旁路字段 INDUSTRY_NAME / INDUSTRY_CODE。

    A 股类型明细资产负债表(G/B/S/I)不含这两个字段 —— 它们是简况
    RPT_DMSK_FN_BALANCE 独有的旁路列,且行业分类跨期恒定。故命中明细报表后
    只发一次请求(仅取最新 1 行)补回,避免整表二次分页拉取。
    quality.get_industry / 选股 max_per_sector 依赖 INDUSTRY_NAME。
    取不到(HK/US 或异常)返回 {},不阻断主流程。
    """
    security_code = code.split(".")[0] if "." in code else code
    params = {
        "reportName": "RPT_DMSK_FN_BALANCE",
        "columns": "ALL",
        "quoteColumns": "",
        "filter": f'(SECURITY_CODE="{security_code}")',
        "pageNumber": 1,
        "pageSize": 1,
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    data = _fetch_page_with_retry(params, code, "RPT_DMSK_FN_BALANCE(industry)")
    if data is None or not data.get("success") or not data.get("result"):
        return {}
    records = data["result"].get("data") or []
    if not records:
        return {}
    out = {}
    for key in ("INDUSTRY_NAME", "INDUSTRY_CODE"):
        val = records[0].get(key)
        if val is not None:
            out[key] = val
    return out


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


def _to_kline_secid(code: str) -> str:
    """标准代码 -> push2his secid。

    HK:    00700.HK  -> 116.00700(5 位带前导 0)
    A股 SH: 600519.SH -> 1.600519
    A股 SZ/BJ: 000001.SZ -> 0.000001
    美股暂不支持(EM secid 前缀依交易所 105/106/107,无法由代码独立推出)。
    """
    if "." not in code:
        raise ValueError(f"无法解析 secid,缺少市场后缀: {code}")
    num, market = code.split(".", 1)
    market = market.upper()
    if market == "HK":
        return f"116.{num.zfill(5)}"
    if market == "SH":
        return f"1.{num.zfill(6)}"
    if market in ("SZ", "BJ"):
        return f"0.{num.zfill(6)}"
    raise ValueError(f"EastMoney K线暂不支持市场: {market} ({code})")


class EastMoneyAdapter(FinancialDataAdapter, EventDataAdapter, MarketDataAdapter):
    """东方财富直接API适配器 — 财务数据 + 分红事件 + 港股行情（2026-10起）"""

    def fetch_income(self, code: str) -> List[IncomeStatement]:
        records = _fetch_report("RPT_DMSK_FN_INCOME", code)
        return _records_to_models(records, IncomeStatement)

    def fetch_balance(self, code: str) -> List[BalanceSheet]:
        """资产负债表 — A 股走 4 张类型明细报表(含商誉/无形/归母权益),
        按普通→银行→券商→保险试,首个非空即用;全空兜底回简况(保聚合字段)。

        明细报表不含行业旁路字段 INDUSTRY_NAME/INDUSTRY_CODE(简况独有),命中后
        补取注入 —— quality.get_industry / 选股 max_per_sector 依赖它;不补会导致
        全市场行业塌成单桶。兜底走简况的路径本就带该字段,无需补。"""
        for report_name in _BALANCE_DETAIL_REPORTS:
            records = _fetch_report(report_name, code)
            if records:
                industry = _fetch_industry_fields(code)
                for rec in records:
                    for key, val in industry.items():
                        rec.setdefault(key, val)
                return _records_to_models(records, BalanceSheet)
        # 全部明细报表为空(HK/US 或极少数特殊 A 股主体)→ 用简况兜底,不回归
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

    # ---------- 日K线(push2his,yfinance 二源交叉校验用) ----------
    def fetch_daily_kline(
        self, code: str, start_date: str, end_date: str, fqt: int = 0
    ) -> List[DailyKlineRecord]:
        """东方财富日K线(push2his)。

        非主行情源 —— 仅用于与 yfinance 港股K线交叉校验(二源数据一致性审计)。
        主行情仍走 yfinance(HK/US)/ baostock(A)。

        Args:
            code: 标准代码,如 00700.HK / 600519.SH(美股暂不支持)
            start_date / end_date: "YYYY-MM-DD"
            fqt: 复权类型 0=不复权(默认,对齐 v_hk_daily_raw)/ 1=前复权 / 2=后复权

        Returns:
            DailyKlineRecord 列表(amount 为真实成交额,区别于 yfinance HK amount 恒 0);
            klines 行内字段序为 日期,开,收,高,低,量,额(close 在 index 2)。
            无数据返 [];网络错误经退避重试仍失败返 []。
        """
        secid = _to_kline_secid(code)
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "klt": 101,  # 日线
            "fqt": fqt,
            "beg": start_date.replace("-", ""),
            "end": end_date.replace("-", ""),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "lmt": 100000,
        }
        # push2his 与 push2 同族,限流敏感:仿浏览器 UA + Referer + Session + 退避重试
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            }
        )
        data = None
        for attempt in range(MAX_RETRIES + 2):
            try:
                resp = session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                data = resp.json()
                break
            except Exception as e:
                if attempt < MAX_RETRIES + 1:
                    time.sleep(RETRY_BASE_DELAY * (2**attempt))
                else:
                    logger.error(f"东方财富K线拉取失败 {code} (secid={secid}): {e}")
                    return []
        if data is None:
            return []

        klines = (data.get("data") or {}).get("klines") or []
        records: List[DailyKlineRecord] = []
        prev_close = None
        for line in klines:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                date_str = parts[0]
                open_ = float(parts[1])
                close = float(parts[2])
                high = float(parts[3])
                low = float(parts[4])
                volume = float(parts[5])
                amount = float(parts[6])
            except (ValueError, IndexError):
                continue
            rec = {
                "date": date_str,
                "code": code,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
            }
            if prev_close is not None and prev_close != 0:
                rec["preclose"] = prev_close
                rec["pctChg"] = (close - prev_close) / prev_close * 100
            prev_close = close
            records.append(DailyKlineRecord(**rec))
        return records

    def fetch_adjust_factor(self, code: str) -> List[AdjustFactorRecord]:
        """港股分红调整因子（Eastmoney口径，2026-10新增）。

        原理（经双源验收验证）：
        - Eastmoney的close_raw出厂已是拆股调整到最新，无需再处理拆股
        - 只需处理分红：div_factor = ∏(1 - D/P)，P为除权日前收盘价
        - 锚定最新日期=1.0（前复权口径，与现有foreAdjustFactor兼容）
        - qfq = close_raw × div_factor

        与yfinance方案的区别：
        - yfinance: foreAdjustFactor含拆股+分红，需audit防幻灵拆股
        - Eastmoney: 拆股已调，只算分红，数据源头干净

        Args:
            code: 标准代码，如 00700.HK

        Returns:
            AdjustFactorRecord列表，按除权日升序。无分红返回[]。
        """
        # 只支持港股，A股/美股走原有adapter
        if not code.endswith(".HK"):
            logger.warning(f"EastMoney fetch_adjust_factor暂只支持港股: {code}")
            return []

        # 1. 获取分红记录
        try:
            dividends = self.fetch_dividends(code)
        except Exception as e:
            logger.error(f"获取分红失败 {code}: {e}")
            return []

        if not dividends:
            return []

        # 2. 获取日线（用于计算D/P的分母P=除权日前收盘）
        # 需要足够长的历史以覆盖所有分红
        try:
            klines = self.fetch_daily_kline(code, "2015-01-01", "2026-12-31", fqt=0)
        except Exception as e:
            logger.error(f"获取K线失败 {code}: {e}")
            return []

        if not klines:
            return []

        # 建日期→收盘价映射
        close_map = {k.date: k.close for k in klines}
        dates_sorted = sorted(close_map.keys())

        # 3. 收集分红事件的factor_change
        # DividendRecord字段：dividOperateDate=除权日，dividCashPsBeforeTax=税前每股现金分红
        events = []  # [(date_str, factor_change)]
        for div in dividends:
            ex_date = div.dividOperateDate
            amount = div.dividCashPsBeforeTax
            if not ex_date or not amount or amount <= 0:
                continue

            # 找除权日前一个交易日的收盘价
            ex_str = str(ex_date)[:10]
            # 找小于ex_date的最大日期
            prev_dates = [d for d in dates_sorted if d < ex_str]
            if not prev_dates:
                continue
            prev_date = max(prev_dates)
            prev_close = close_map[prev_date]
            if prev_close <= 0:
                continue

            factor_change = (prev_close - amount) / prev_close
            if factor_change <= 0 or factor_change > 1:
                continue
            events.append((ex_str, factor_change))

        if not events:
            return []

        # 4. 同日合并（同一除权日多笔分红）
        merged: dict[str, float] = {}
        for date_str, change in events:
            merged[date_str] = merged.get(date_str, 1.0) * change
        events = sorted(merged.items(), key=lambda x: x[0])

        # 5. 从后往前累乘，锚定最新=1.0
        n = len(events)
        fore_factors = [0.0] * n
        fore_factors[n - 1] = 1.0
        for i in range(n - 2, -1, -1):
            fore_factors[i] = fore_factors[i + 1] * events[i + 1][1]

        # 6. 标准化代码格式（5位HK代码）
        std_code = code
        if code.endswith(".HK"):
            num = code.split(".")[0].lstrip("0") or "0"
            std_code = f"{num.zfill(5)}.HK"

        records = [
            AdjustFactorRecord(
                code=std_code,
                dividOperateDate=date_str,
                foreAdjustFactor=round(factor, 6),
            )
            for (date_str, _), factor in zip(events, fore_factors)
        ]
        return records

    # ---------- 港股通成分股(push2 行情板块接口) ----------
    # 板块代码:
    #   b:DLMK0146 = 港股通(沪)+ 港股通(深)合并 ~601 只(含全部南向标的)
    #   b:DLMK0144 = 港股通(沪)
    #   b:DLMK0145 = 港股通(深独有)~69 只
    # 仅返回当前快照(无历史进出名单)
    def fetch_hk_connect_members(self, board_code: str = "DLMK0146") -> List[dict]:
        """港股通成分股当前快照。

        Args:
            board_code: 板块代码,默认 DLMK0146(港股通全集)

        Returns:
            [{"code": "09988", "name": "阿里巴巴-W"}, ...] — code 为 5 位 HK 代码(带前导 0)
            失败返 []。
        """
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        page_size = 100  # push2 接口单页上限 100,需分页
        out: List[dict] = []
        seen = set()
        # 用 Session 复用连接 + 仿浏览器 UA,降低 push2 限流概率
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            }
        )
        for page in range(1, 50):  # 安全上限 5000 只
            params = {
                "pn": page,
                "pz": page_size,
                "fs": f"b:{board_code}",
                "fields": "f12,f14",
                "fid": "f12",
                "po": 1,
            }
            page_data = None
            for attempt in range(MAX_RETRIES + 2):  # 港股通分页给更多重试机会
                try:
                    resp = session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                    page_data = resp.json()
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES + 1:
                        time.sleep(RETRY_BASE_DELAY * (2**attempt))
                    else:
                        logger.error(
                            f"港股通成分股拉取失败 board={board_code} page={page}: {e}"
                        )
                        return out
            if page_data is None:
                break
            diff = (page_data.get("data") or {}).get("diff") or {}
            items = diff.values() if isinstance(diff, dict) else diff
            page_count = 0
            for it in items:
                code = str(it.get("f12") or "").strip()
                name = str(it.get("f14") or "").strip()
                if code and name and code not in seen:
                    seen.add(code)
                    out.append({"code": code, "name": name})
                    page_count += 1
            if page_count == 0:
                break
            time.sleep(1.0)  # push2 限流敏感,每页间隔 1s
        return out

    def fetch_hk_connect_members_holdrank(self) -> List[dict]:
        """港股通成分股 — datacenter-web fallback(push2 限流时使用)。

        通过 RPT_MUTUAL_STOCK_HOLDRANKS 报表获取最新 HOLD_DATE 的全部南向标的。
        MUTUAL_TYPE: 002=沪市港股通 / 004=深市港股通,同一股票常出现两次,按
        SECURITY_CODE 去重。

        Returns:
            [{"code": "09988", "name": "阿里巴巴-W"}, ...] 与 push2 版本同 schema
            失败返 []。
        """
        host = "datacenter-web.eastmoney.com"
        url = f"https://{host}/api/data/v1/get"
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
                ),
                "Referer": "https://data.eastmoney.com/",
            }
        )

        # Step 1:取最新 HOLD_DATE
        latest_date: Optional[str] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = session.get(
                    url,
                    params={
                        "reportName": "RPT_MUTUAL_STOCK_HOLDRANKS",
                        "columns": "HOLD_DATE",
                        "pageNumber": "1",
                        "pageSize": "1",
                        "sortColumns": "HOLD_DATE",
                        "sortTypes": "-1",
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
                payload = resp.json()
                rows = (payload.get("result") or {}).get("data") or []
                if rows and rows[0].get("HOLD_DATE"):
                    # 截前 10 字符,YYYY-MM-DD HH:MM:SS → YYYY-MM-DD
                    latest_date = str(rows[0]["HOLD_DATE"])[:10]
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY * (2**attempt))
                else:
                    logger.error(f"holdrank 取最新 HOLD_DATE 失败: {e}")
                    return []
        if not latest_date:
            logger.warning("holdrank: 无最新 HOLD_DATE")
            return []

        # Step 2:分页拉全量(pageSize 服务端实际上限 ~500,留余量取 500)
        out: List[dict] = []
        seen = set()
        page_size = 500
        for page in range(1, 50):  # 安全上限
            page_data = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    resp = session.get(
                        url,
                        params={
                            "reportName": "RPT_MUTUAL_STOCK_HOLDRANKS",
                            "columns": "SECUCODE,SECURITY_CODE,SECURITY_NAME,MUTUAL_TYPE",
                            "pageNumber": str(page),
                            "pageSize": str(page_size),
                            "filter": f"(HOLD_DATE='{latest_date}')",
                        },
                        timeout=DEFAULT_TIMEOUT,
                    )
                    page_data = resp.json()
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_BASE_DELAY * (2**attempt))
                    else:
                        logger.error(f"holdrank page {page} 失败: {e}")
                        return out
            if page_data is None or not page_data.get("success"):
                break
            rows = (page_data.get("result") or {}).get("data") or []
            if not rows:
                break
            page_count = 0
            for it in rows:
                secucode = str(it.get("SECUCODE") or "")
                # 仅保留 .HK 后缀(防御性,理论上 002/004 都是 HK)
                if not secucode.endswith(".HK"):
                    continue
                code = str(it.get("SECURITY_CODE") or "").strip()
                name = str(it.get("SECURITY_NAME") or "").strip()
                if code and name and code not in seen:
                    seen.add(code)
                    out.append({"code": code, "name": name})
                    page_count += 1
            # 不足一页 → 已到末页
            if len(rows) < page_size:
                break
            time.sleep(0.3)
        logger.info(f"holdrank: HOLD_DATE={latest_date} 去重后 {len(out)} 只港股通")
        return out

    def login(self):
        """兼容 BaoStockAdapter 接口,EastMoney 无需登录。"""
        pass

    def logout(self):
        pass
