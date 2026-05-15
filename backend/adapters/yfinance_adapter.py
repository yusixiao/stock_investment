import logging
from typing import List, Optional

import pandas as pd
import yfinance as yf

from backend.adapters.base import MarketDataAdapter
from backend.models.market import DailyKlineRecord, AdjustFactorRecord

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


class YFinanceAdapter(MarketDataAdapter):
    """yfinance 数据源适配器 — 用于港股行情数据"""

    def fetch_daily_kline(
        self, code: str, start_date: str, end_date: str
    ) -> List[DailyKlineRecord]:
        yf_code = _to_yfinance_code(code)
        std_code = _to_standard_code(yf_code)

        try:
            t = yf.Ticker(yf_code)
            df = t.history(start=start_date, end=end_date, auto_adjust=False)
        except Exception as e:
            logger.error(f"yfinance fetch_daily_kline failed for {code}: {e}")
            return []

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

        try:
            t = yf.Ticker(yf_code)
            df = t.history(period="max", auto_adjust=False)
        except Exception as e:
            logger.error(f"yfinance fetch_daily_kline_full failed for {code}: {e}")
            return []

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

        try:
            t = yf.Ticker(yf_code)
            hist = t.history(period="max", auto_adjust=False)
            divs = t.dividends
            splits = t.splits
        except Exception as e:
            logger.error(f"yfinance fetch_adjust_factor failed for {code}: {e}")
            return []

        if hist.empty:
            return []

        # 收集所有除权事件（分红+拆股）及其因子变化
        events = []

        for dt, amount in divs.items():
            if amount <= 0:
                continue
            mask = hist.index < dt
            if not mask.any():
                continue
            prev_close = float(hist.loc[mask].iloc[-1]["Close"])
            if prev_close <= 0:
                continue
            factor_change = (prev_close - amount) / prev_close
            date_str = dt.strftime("%Y-%m-%d")
            events.append((date_str, factor_change))

        for dt, ratio in splits.items():
            if ratio <= 0 or ratio == 1.0:
                continue
            date_str = dt.strftime("%Y-%m-%d")
            # 拆股 N:1 意味着价格除以 N，因子乘以 1/N
            events.append((date_str, 1.0 / ratio))

        if not events:
            return []

        # 按日期排序（升序）
        events.sort(key=lambda x: x[0])

        # 计算前复权因子：从最新事件往前累乘
        # foreAdjustFactor 在最新事件日为最接近 1.0 的值
        # 从后往前：factor[i] = factor[i+1] * factor_change[i+1]
        n = len(events)
        fore_factors = [0.0] * n

        # 从最后一个事件开始，其 foreAdjustFactor = 1.0
        fore_factors[n - 1] = 1.0
        for i in range(n - 2, -1, -1):
            fore_factors[i] = fore_factors[i + 1] * events[i + 1][1]

        records = []
        for i, (date_str, _) in enumerate(events):
            records.append(
                AdjustFactorRecord(
                    code=std_code,
                    dividOperateDate=date_str,
                    foreAdjustFactor=round(fore_factors[i], 6),
                )
            )

        return records
