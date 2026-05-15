import logging
from contextlib import contextmanager
from typing import List, Optional

import baostock as bs
import pandas as pd

from backend.adapters.base import MarketDataAdapter, BasicDataAdapter, EventDataAdapter
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.basic import StockBasicInfo
from backend.models.event import DividendRecord

logger = logging.getLogger(__name__)

KLINE_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)

FLOAT_COLS = [
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "turn",
    "pctChg",
    "peTTM",
    "pbMRQ",
    "psTTM",
    "pcfNcfTTM",
]


def _to_baostock_code(code: str) -> str:
    """000001.SZ -> sz.000001"""
    parts = code.split(".")
    if len(parts) == 2:
        return f"{parts[1].lower()}.{parts[0]}"
    return code


def _to_standard_code(bs_code: str) -> str:
    """sz.000001 -> 000001.SZ"""
    parts = bs_code.split(".")
    if len(parts) == 2:
        return f"{parts[1]}.{parts[0].upper()}"
    return bs_code


@contextmanager
def _baostock_session():
    lg = bs.login()
    if lg.error_code != "0":
        raise ConnectionError(f"BaoStock login failed: {lg.error_msg}")
    try:
        yield
    finally:
        bs.logout()


def _result_to_df(rs) -> pd.DataFrame:
    rows = []
    while (rs.error_code == "0") and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=rs.fields)


class BaoStockAdapter(MarketDataAdapter, BasicDataAdapter, EventDataAdapter):
    """BaoStock 数据源适配器 — 实现行情、基本信息、事件接口"""

    def __init__(self):
        self._logged_in = False

    def login(self):
        """手动登录，用于批量操作时保持长连接"""
        if not self._logged_in:
            lg = bs.login()
            if lg.error_code != "0":
                raise ConnectionError(f"BaoStock login failed: {lg.error_msg}")
            self._logged_in = True

    def logout(self):
        """手动登出"""
        if self._logged_in:
            bs.logout()
            self._logged_in = False

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *args):
        self.logout()

    def fetch_daily_kline(
        self, code: str, start_date: str, end_date: str
    ) -> List[DailyKlineRecord]:
        bs_code = _to_baostock_code(code)
        auto_session = not self._logged_in
        if auto_session:
            self.login()
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                KLINE_FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3",
            )
            df = _result_to_df(rs)
        finally:
            if auto_session:
                self.logout()

        if df.empty:
            return []

        for col in FLOAT_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["code"] = code

        records = []
        for _, row in df.iterrows():
            data = {}
            for field in DailyKlineRecord.model_fields:
                val = row.get(field)
                if (
                    val is not None
                    and val != ""
                    and not (isinstance(val, float) and pd.isna(val))
                ):
                    data[field] = val
            if "volume" not in data:
                data["volume"] = 0.0
            if "amount" not in data:
                data["amount"] = 0.0
            records.append(DailyKlineRecord(**data))

        return records

    def fetch_adjust_factor(self, code: str) -> List[AdjustFactorRecord]:
        bs_code = _to_baostock_code(code)
        auto_session = not self._logged_in
        if auto_session:
            self.login()
        try:
            rs = bs.query_adjust_factor(code=bs_code)
            df = _result_to_df(rs)
        finally:
            if auto_session:
                self.logout()

        if df.empty:
            return []

        df["foreAdjustFactor"] = pd.to_numeric(df["foreAdjustFactor"], errors="coerce")
        if "backAdjustFactor" in df.columns:
            df["backAdjustFactor"] = pd.to_numeric(
                df["backAdjustFactor"], errors="coerce"
            )
        if "adjustFactor" in df.columns:
            df["adjustFactor"] = pd.to_numeric(df["adjustFactor"], errors="coerce")

        df["code"] = code

        records = []
        for _, row in df.iterrows():
            data = {
                "code": code,
                "dividOperateDate": row.get("dividOperateDate", ""),
                "foreAdjustFactor": row["foreAdjustFactor"],
            }
            if "backAdjustFactor" in row and pd.notna(row["backAdjustFactor"]):
                data["backAdjustFactor"] = row["backAdjustFactor"]
            if "adjustFactor" in row and pd.notna(row["adjustFactor"]):
                data["adjustFactor"] = row["adjustFactor"]
            records.append(AdjustFactorRecord(**data))

        return records

    def fetch_stock_list(self) -> List[StockBasicInfo]:
        auto_session = not self._logged_in
        if auto_session:
            self.login()
        try:
            rs = bs.query_stock_basic()
            df_basic = _result_to_df(rs)
        finally:
            if auto_session:
                self.logout()

        if df_basic.empty:
            return []

        records = []
        for _, row in df_basic.iterrows():
            bs_code = row.get("code", "")
            std_code = _to_standard_code(bs_code)
            records.append(
                StockBasicInfo(
                    code=std_code,
                    name=row.get("code_name", ""),
                    ipo_date=row.get("ipoDate", ""),
                    delist_date=row.get("outDate") if row.get("outDate") else None,
                    stock_type=row.get("type") if row.get("type") else None,
                    status=row.get("status", "1"),
                    industry=row.get("industry") if row.get("industry") else None,
                )
            )

        return records

    def fetch_dividends(
        self, code: str, year: Optional[str] = None
    ) -> List[DividendRecord]:
        bs_code = _to_baostock_code(code)
        year_key = year or ""
        auto_session = not self._logged_in
        if auto_session:
            self.login()
        try:
            rs = bs.query_dividend_data(code=bs_code, year=year_key)
            df = _result_to_df(rs)
        finally:
            if auto_session:
                self.logout()

        if df.empty:
            return []

        float_fields = [
            "dividCashPsBeforeTax",
            "dividStocksPs",
            "dividReserveToStockPs",
        ]
        for col in float_fields:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        records = []
        for _, row in df.iterrows():
            data = {"code": code}
            for field in DividendRecord.model_fields:
                if field == "code":
                    continue
                val = row.get(field)
                if (
                    val is not None
                    and val != ""
                    and not (isinstance(val, float) and pd.isna(val))
                ):
                    data[field] = val
            records.append(DividendRecord(**data))

        return records
