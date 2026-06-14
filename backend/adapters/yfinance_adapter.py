import logging
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import yfinance as yf

from backend.adapters.base import MarketDataAdapter, EventDataAdapter
from backend.models.market import DailyKlineRecord, AdjustFactorRecord
from backend.models.event import DividendRecord
from backend.models.management import ExecutiveRecord, ExecutiveHoldChangeRecord
from backend.services.market_data.adjust_factor_audit import audit_factors, recompute_factors

logger = logging.getLogger(__name__)


def _to_yfinance_code(code: str) -> str:
    """00700.HK -> 0700.HK (yfinance 用4位数字)"""
    parts = code.split(".")
    if len(parts) == 2 and parts[1] == "HK":
        num = parts[0].lstrip("0") or "0"
        return f"{num.zfill(4)}.HK"
    return code


def _to_standard_code(yf_code: str) -> str:
    """0700.HK -> 00700.HK (标准5位港股代码)"""
    parts = yf_code.split(".")
    if len(parts) == 2 and parts[1] == "HK":
        return f"{parts[0].zfill(5)}.HK"
    return yf_code


class YFinanceAdapter(MarketDataAdapter, EventDataAdapter):
    """yfinance 数据源适配器 — 港股/美股行情 + 每股分红事件。"""

    def fetch_daily_kline(
        self, code: str, start_date: str, end_date: str
    ) -> List[DailyKlineRecord]:
        yf_code = _to_yfinance_code(code)
        std_code = _to_standard_code(yf_code)

        # 不吞异常: rate-limit / network 错误向上抛供 _fetch_with_retry 重试;
        # 真正空数据(delisted / 区间无交易)yfinance 返回 df.empty 而不抛
        # yfinance/Yahoo 用半开区间 [start, end),为了让 end_date 当天也被包含,
        # 把 end_date +1 天传给 yf;否则 start==end 时 Yahoo 返回 400 触发内部慢重试
        yf_end = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        t = yf.Ticker(yf_code)
        df = t.history(start=start_date, end=yf_end, auto_adjust=False)

        if df.empty:
            return []

        records = []
        prev_close = None
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            volume = float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0
            close = float(row["Close"])
            data = {
                "date": date_str,
                "code": std_code,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": close,
                "volume": volume,
                "amount": 0.0,
            }
            if prev_close is not None:
                data["preclose"] = prev_close
                data["pctChg"] = (close - prev_close) / prev_close * 100
            prev_close = close
            records.append(DailyKlineRecord(**data))

        return records

    def fetch_daily_kline_full(self, code: str) -> List[DailyKlineRecord]:
        """获取全量历史日K线"""
        yf_code = _to_yfinance_code(code)
        std_code = _to_standard_code(yf_code)

        # 同 fetch_daily_kline: 不吞异常,让 retry 层处理可重试错误
        t = yf.Ticker(yf_code)
        df = t.history(period="max", auto_adjust=False)

        if df.empty:
            return []

        records = []
        prev_close = None
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            volume = float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0
            close = float(row["Close"])
            data = {
                "date": date_str,
                "code": std_code,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": close,
                "volume": volume,
                "amount": 0.0,
            }
            if prev_close is not None:
                data["preclose"] = prev_close
                data["pctChg"] = (close - prev_close) / prev_close * 100
            prev_close = close
            records.append(DailyKlineRecord(**data))

        return records

    def fetch_adjust_factor(self, code: str) -> List[AdjustFactorRecord]:
        """从 dividends + splits 计算前复权因子"""
        yf_code = _to_yfinance_code(code)
        std_code = _to_standard_code(yf_code)

        # 不吞异常,让 retry 层处理
        t = yf.Ticker(yf_code)
        hist = t.history(period="max", auto_adjust=False)
        divs = t.dividends
        splits = t.splits

        if hist.empty:
            return []

        # 收集所有除权事件（分红+拆股）及其因子变化
        events = []

        for dt, amount in divs.items():
            # yfinance 偶尔返回 NaN 分红额(NaN <= 0 为 False 会漏过判断,
            # 进而产出 NaN factor_change → 累计因子全 None,污染该标的 qfq)
            if amount is None or pd.isna(amount) or amount <= 0:
                continue
            mask = hist.index < dt
            if not mask.any():
                continue
            prev_close = float(hist.loc[mask].iloc[-1]["Close"])
            if prev_close <= 0 or pd.isna(prev_close):
                continue
            factor_change = (prev_close - amount) / prev_close
            if pd.isna(factor_change) or factor_change <= 0:
                continue
            date_str = dt.strftime("%Y-%m-%d")
            events.append((date_str, factor_change))

        for dt, ratio in splits.items():
            if ratio is None or pd.isna(ratio) or ratio <= 0 or ratio == 1.0:
                continue
            date_str = dt.strftime("%Y-%m-%d")
            # 拆股 N:1 意味着价格除以 N，因子乘以 1/N
            events.append((date_str, 1.0 / ratio))

        if not events:
            return []

        # 同一除权日可能同时发生多个公司行为(如分红+拆股、分红+送股)。
        # 必须先把同日所有 factor_change 连乘合并成一个,否则后续累乘会为
        # 同一 dividOperateDate 产出多条因子不同的行 → 写入 parquet 后该日键
        # 非唯一,qfq ASOF JOIN 在并行下随机选行,导致回测结果不可复现。
        merged: dict[str, float] = {}
        for date_str, change in events:
            merged[date_str] = merged.get(date_str, 1.0) * change
        events = sorted(merged.items(), key=lambda x: x[0])

        # 计算前复权因子：从最新事件往前累乘
        # foreAdjustFactor 在最新事件日为最接近 1.0 的值
        # 从后往前：factor[i] = factor[i+1] * factor_change[i+1]
        n = len(events)
        fore_factors = [0.0] * n

        # 从最后一个事件开始，其 foreAdjustFactor = 1.0
        fore_factors[n - 1] = 1.0
        for i in range(n - 2, -1, -1):
            fore_factors[i] = fore_factors[i + 1] * events[i + 1][1]

        recs = [(events[i][0], round(fore_factors[i], 6)) for i in range(n)]

        # 幻灵拆股防线(2026-06):yfinance t.splits 偶尔返回真实股价中并不存在的
        # 拆股事件(BYD 01211.HK 2025 假涨 +1910% 事故)。用 raw close 跳空比校验每个
        # 大额 factor_change:真实拆股/合股必在 hist Close 留对应跳空,幻灵则 raw 平稳。
        # 不匹配者中性化并重算,避免每日 06:00 更新重新污染存量数据。
        raw = [
            (idx.strftime("%Y-%m-%d"), float(c))
            for idx, c in zip(hist.index, hist["Close"])
            if c is not None and not pd.isna(c) and c > 0
        ]
        raw.sort(key=lambda x: x[0])
        audited = audit_factors(recs, raw)
        cleaned = recompute_factors(audited)

        records = [
            AdjustFactorRecord(
                code=std_code,
                dividOperateDate=date_str,
                foreAdjustFactor=factor,
            )
            for date_str, factor in cleaned
        ]

        return records

    def fetch_dividends(
        self, code: str, year: Optional[str] = None
    ) -> List[DividendRecord]:
        """获取每股分红事件序列(yfinance.Ticker.dividends)。

        yfinance dividends 返回 pandas Series,index=ex-dividend date(本币每股金额)。
        映射到 DividendRecord 的 BaoStock 字段以与 A 股 schema 对齐:
          - dividOperateDate = ex-dividend date(YYYY-MM-DD)
          - dividCashPsBeforeTax = 每股分红(本币,yfinance 默认税前)
          其余 dividRegistDate / dividPayDate / dividStocksPs 等字段 yfinance 不提供,留空。

        参数 year 暂未使用(yfinance 一次性返回全部历史,与 EastMoneyAdapter 行为一致)。
        """
        yf_code = _to_yfinance_code(code)
        std_code = _to_standard_code(yf_code)
        t = yf.Ticker(yf_code)
        divs = t.dividends
        if divs is None or divs.empty:
            return []
        records: List[DividendRecord] = []
        for dt, amount in divs.items():
            try:
                amt = float(amount)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            date_str = dt.strftime("%Y-%m-%d")
            records.append(
                DividendRecord(
                    code=std_code,
                    dividOperateDate=date_str,
                    dividCashPsBeforeTax=amt,
                )
            )
        return records

    # ---------- D4 管理层(HK / US) ----------
    # 2026-05-26 spike 验证:emweb 不支持 HK/US,改用 yfinance
    # - Ticker.info["companyOfficers"] ~10 条核心高管
    # - Ticker.insider_transactions DataFrame ~30-100 条变动
    def fetch_company_management(
        self, code: str
    ) -> tuple[List[ExecutiveRecord], List[ExecutiveHoldChangeRecord]]:
        """高管列表 + 内部人交易(HK / US)。失败/空返 ([], [])。

        yfinance 字段差异(对 ExecutiveRecord 模型的影响):
        - 仅有 name / title / age(由 yearBorn 推算)/ totalPay
        - 无 sex / education / tenure_text / resume(全留空)

        insider_transactions:
        - Shares(股数,正负不区分,方向看 Transaction 列文本)
        - Value / Text / Insider / Position / Transaction / Start Date
        """
        yf_code = _to_yfinance_code(code)
        try:
            t = yf.Ticker(yf_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"D4 yfinance Ticker init 失败 {code}: {exc}")
            return [], []

        executives = _yf_officers_to_executives(t)
        hold_changes = _yf_insider_to_hold_changes(t)
        return executives, hold_changes


def _yf_officers_to_executives(t) -> List[ExecutiveRecord]:
    """Ticker.info['companyOfficers'] → ExecutiveRecord 列表。"""
    try:
        info = t.info or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"yfinance Ticker.info 失败: {exc}")
        return []
    officers = info.get("companyOfficers") or []
    if not isinstance(officers, list):
        return []

    out: List[ExecutiveRecord] = []
    for it in officers:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        # age 优先取 age,缺则用 fiscalYear - yearBorn 兜底
        age = it.get("age")
        if age is None and it.get("yearBorn") and it.get("fiscalYear"):
            try:
                age = int(it["fiscalYear"]) - int(it["yearBorn"])
            except (TypeError, ValueError):
                age = None
        try:
            out.append(
                ExecutiveRecord(
                    name=name,
                    position=it.get("title"),
                    age=int(age) if age is not None else None,
                    salary=float(it["totalPay"])
                    if it.get("totalPay") is not None
                    else None,
                    source="yfinance",
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"yfinance officer 解析跳过 {name}: {e}")
    return out


def _yf_insider_to_hold_changes(t) -> List[ExecutiveHoldChangeRecord]:
    """Ticker.insider_transactions → ExecutiveHoldChangeRecord 列表。

    yfinance 这张表方向(增/减)藏在 'Transaction' 列文本(如 'Sale' / 'Purchase' /
    'Stock Gift' / 'Statement of Ownership'),Shares 列本身**不带符号**。
    我们只对包含 Sale/Sell/Disposition/Buy/Purchase/Acquisition 关键字的行处理。
    """
    try:
        df = t.insider_transactions
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"yfinance insider_transactions 失败: {exc}")
        return []
    if df is None or getattr(df, "empty", True):
        return []

    out: List[ExecutiveHoldChangeRecord] = []
    for _, row in df.iterrows():
        try:
            insider = str(row.get("Insider") or "").strip()
            if not insider:
                continue
            txn = str(row.get("Transaction") or "")
            txn_low = txn.lower()
            shares = row.get("Shares")
            try:
                shares_val = float(shares) if pd.notna(shares) else None
            except (TypeError, ValueError):
                shares_val = None
            if shares_val is None:
                continue
            # 方向判定:能识别再处理,识别不出来跳过
            if any(k in txn_low for k in ("sale", "sell", "disposition")):
                change_num = -abs(shares_val)
            elif any(
                k in txn_low for k in ("buy", "purchase", "acquisition", "exercise")
            ):
                change_num = abs(shares_val)
            else:
                continue
            start_date = row.get("Start Date")
            try:
                date_str = pd.to_datetime(start_date).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                continue
            value = row.get("Value")
            avg_price = None
            try:
                if pd.notna(value) and shares_val:
                    avg_price = float(value) / abs(shares_val)
            except (TypeError, ValueError, ZeroDivisionError):
                avg_price = None
            out.append(
                ExecutiveHoldChangeRecord(
                    end_date=date_str,
                    executive_name=insider,
                    position=str(row.get("Position") or "") or None,
                    change_num=change_num,
                    average_price=avg_price,
                    trade_way=txn or None,
                    executive_relation=str(row.get("Ownership") or "") or None,
                    source="yfinance",
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"yfinance insider 行解析跳过: {e}")
    # 按日期降序
    out.sort(key=lambda r: r.end_date, reverse=True)
    return out
