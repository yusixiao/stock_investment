import logging
import socket
import threading
from contextlib import contextmanager
from typing import List, Optional

import baostock as bs
import pandas as pd

from backend.adapters.base import MarketDataAdapter, BasicDataAdapter, EventDataAdapter
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.basic import StockBasicInfo
from backend.models.event import DividendRecord

logger = logging.getLogger(__name__)

# BaoStock 底层 socket 默认无超时，服务端不响应时 recv/connect 会永久阻塞
# (2026-06-29 事故：手动重跑卡死 1.5h，login 亦曾卡 19min)。用 setdefaulttimeout
# 让 login 时创建的 socket 继承该超时——socket 创建后自带超时值，随后恢复 default
# 既不影响已建连接，也不污染进程内其它 socket。recv/connect 超时会抛异常，
# 交由上层 _retry_call / _fetch_with_retry 重试，避免线程永久挂起。
BAOSTOCK_SOCKET_TIMEOUT = 30.0


@contextmanager
def _socket_timeout(seconds: float):
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old)


# BaoStock 数据端口(:10030)的 socket 不遵守 setdefaulttimeout —— 已实测(2026-07-01):
# 对查询套 0.5s 默认超时,查询仍耗时 2.2s 正常返回,超时未触发。服务端在建连后把
# socket 置回阻塞模式,故 socket 级超时对数据读取完全无效;服务端"僵而不断"(recv
# 永久阻塞)时会拖死整个更新(2026-06-29 卡 1.5h、2026-07-01 卡 8.7h)。只能用墙钟
# 看门狗从外部兜底 —— 见 _run_with_timeout。正常查询 1~3s,过载时实测最慢 ~22s,
# 取 45s 作硬超时上限(留足余量,避免误杀合法的慢查询)。
BAOSTOCK_QUERY_TIMEOUT = 45.0


def _run_with_timeout(fn, timeout: float, label: str):
    """在守护线程中执行阻塞的 BaoStock 调用,超过 timeout 秒仍未返回即判定连接
    僵死,抛 TimeoutError 交由上层 _retry_call 重试(而非永久挂起整个更新)。

    市场内取数为串行(market_updater 单线程 for 循环),不会有并发 BaoStock 调用
    竞争全局连接。僵死的 worker 为 daemon 线程,会在旧 socket 最终报错时自行退出,
    不阻止进程结束。fn 内的异常按原样透传回主线程重新抛出。
    """
    box: dict = {}

    def _worker():
        try:
            box["value"] = fn()
        except BaseException as e:  # 透传给主线程按原样重新抛出
            box["error"] = e

    t = threading.Thread(target=_worker, name=f"bs-{label}", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(
            f"BaoStock call hung >{timeout}s (unresponsive connection): {label}"
        )
    if "error" in box:
        raise box["error"]
    return box.get("value")


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
    with _socket_timeout(BAOSTOCK_SOCKET_TIMEOUT):
        lg = bs.login()
    if lg.error_code != "0":
        raise ConnectionError(f"BaoStock login failed: {lg.error_msg}")
    try:
        yield
    finally:
        bs.logout()


def _result_to_df(rs) -> pd.DataFrame:
    """读取 BaoStock 结果集为 DataFrame。

    BaoStock 用 error_code 字段表示错误(网络/限流/系统等),不抛异常。
    若发生错误,这里 raise RuntimeError 让 _fetch_with_retry 重试,
    避免被静默吞成空 DataFrame → market_updater 误计 skipped。
    """
    if rs.error_code != "0":
        raise RuntimeError(
            f"BaoStock error_code={rs.error_code}, error_msg={rs.error_msg}"
        )
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
        # next() 内部也可能切换到错误状态(分页拉取中断等)
        if rs.error_code != "0":
            raise RuntimeError(
                f"BaoStock error_code={rs.error_code} during pagination, "
                f"error_msg={rs.error_msg}"
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=rs.fields)


class BaoStockAdapter(MarketDataAdapter, BasicDataAdapter, EventDataAdapter):
    """BaoStock 数据源适配器 — 实现行情、基本信息、事件接口"""

    def __init__(self):
        self._logged_in = False

    @staticmethod
    def _raw_login():
        with _socket_timeout(BAOSTOCK_SOCKET_TIMEOUT):
            return bs.login()

    def login(self):
        """手动登录，用于批量操作时保持长连接"""
        if not self._logged_in:
            # login 底层 socket 也可能僵死(2026-06-29 曾卡 19min),同样套墙钟看门狗
            lg = _run_with_timeout(self._raw_login, BAOSTOCK_QUERY_TIMEOUT, "login")
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

    def _query_with_watchdog(self, query_fn, label: str, auto_session: bool):
        """执行 query_fn() 并把结果读成 DataFrame,套墙钟看门狗防僵死。

        超时(连接僵死)时:丢弃当前会话;若原为批量长连接(auto_session=False),
        立即重建长连接,避免退化成每股重新登录;随后把 TimeoutError 抛出,交由
        上层 _retry_call 按退避策略重试。
        """
        try:
            return _run_with_timeout(
                lambda: _result_to_df(query_fn()), BAOSTOCK_QUERY_TIMEOUT, label
            )
        except TimeoutError:
            self._logged_in = False
            if not auto_session:
                try:
                    self.login()  # 重建长连接,保持后续增量取数复用
                except Exception:
                    pass  # 重登录失败留待下次调用自然重试
            raise

    def fetch_daily_kline(
        self, code: str, start_date: str, end_date: str
    ) -> List[DailyKlineRecord]:
        bs_code = _to_baostock_code(code)
        auto_session = not self._logged_in
        if auto_session:
            self.login()
        try:
            df = self._query_with_watchdog(
                lambda: bs.query_history_k_data_plus(
                    bs_code,
                    KLINE_FIELDS,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="3",
                ),
                f"kline {code}",
                auto_session,
            )
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
            df = self._query_with_watchdog(
                lambda: bs.query_adjust_factor(code=bs_code),
                f"adjust_factor {code}",
                auto_session,
            )
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
            df_basic = self._query_with_watchdog(
                lambda: bs.query_stock_basic(), "stock_basic", auto_session
            )
            # query_stock_basic 实际不返回 industry,需另调 query_stock_industry merge
            try:
                df_ind = self._query_with_watchdog(
                    lambda: bs.query_stock_industry(), "stock_industry", auto_session
                )
            except Exception:
                df_ind = None
        finally:
            if auto_session:
                self.logout()

        if df_basic.empty:
            return []

        # 构 bs_code -> industry 映射(部分股票无行业,缺失即 None)
        ind_map: dict[str, str] = {}
        if df_ind is not None and not df_ind.empty and "industry" in df_ind.columns:
            for _, row in df_ind.iterrows():
                code = row.get("code", "")
                ind = row.get("industry", "")
                if code and ind:
                    ind_map[code] = ind

        records = []
        for _, row in df_basic.iterrows():
            bs_code = row.get("code", "")
            std_code = _to_standard_code(bs_code)
            industry = ind_map.get(bs_code) or row.get("industry") or None
            records.append(
                StockBasicInfo(
                    code=std_code,
                    name=row.get("code_name", ""),
                    ipo_date=row.get("ipoDate", ""),
                    delist_date=row.get("outDate") if row.get("outDate") else None,
                    stock_type=row.get("type") if row.get("type") else None,
                    status=row.get("status", "1"),
                    industry=industry,
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
            df = self._query_with_watchdog(
                lambda: bs.query_dividend_data(code=bs_code, year=year_key),
                f"dividend {code}",
                auto_session,
            )
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
