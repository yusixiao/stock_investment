"""MarketData 适配器(2026-05-22 升级:接受预算 weekly/monthly + 提供 get_indicator)。

被 ``BacktestEngine`` 直接构造,封装 stock_data dict + 周/月聚合缓存,
并对外暴露 ``Context`` 所需的最小数据访问 API。

设计要点:
- 输入:``stock_data`` (daily,带预算指标列) + 可选 ``weekly_data`` / ``monthly_data``
  (data_cache 加载时已聚合并预算指标);未提供时 fallback 到运行时按需聚合(测试用)
- ``dates``:以 stock_data 中第一只股票的全历史日历为参考,**不裁剪**
- iter_start/iter_end 由 Engine 决定迭代窗口,MarketData 不参与
- 持仓相关 API 由 Broker 提供,本类不负责
- get_indicator(symbol, name, period, idx, **kwargs):查表式 O(1) 取指标,
  命中标准列(由 indicators.resolve_indicator_column 决定)即返回,否则 None
- valuation/financial 不变,沿用预编译 _StaticTable
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from services.backtest.indicators import compute_indicators, resolve_indicator_column
from services.stock_data import aggregate_kline


class _StaticTable:
    """valuation/financial 的预编译缓存(列存 + 升序 date)。"""

    __slots__ = ("dates", "num_cols", "obj_cols", "n")

    def __init__(
        self,
        dates: np.ndarray,
        num_cols: dict[str, np.ndarray],
        obj_cols: dict[str, np.ndarray],
    ):
        self.dates = dates
        self.num_cols = num_cols
        self.obj_cols = obj_cols
        self.n = len(dates)


def _build_static_table(
    df: pd.DataFrame, date_col: str, ffill: bool = True
) -> _StaticTable:
    if df is None or df.empty or date_col not in df.columns:
        return _StaticTable(np.array([], dtype=object), {}, {})
    df = df.sort_values(date_col).reset_index(drop=True)
    dates_raw = df[date_col]
    if len(dates_raw) > 0 and not isinstance(dates_raw.iloc[0], str):
        dates_arr = dates_raw.astype(str).to_numpy()
    else:
        dates_arr = dates_raw.to_numpy()

    num_cols: dict[str, np.ndarray] = {}
    obj_cols: dict[str, np.ndarray] = {}
    for col in df.columns:
        if col == date_col:
            continue
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            arr = series.to_numpy(dtype=float, copy=True)
            if ffill:
                mask = np.isnan(arr)
                if mask.any():
                    idx = np.where(~mask, np.arange(len(arr)), 0)
                    np.maximum.accumulate(idx, out=idx)
                    arr = arr[idx]
                    first_valid = (~mask).argmax() if (~mask).any() else len(arr)
                    if first_valid > 0:
                        arr[:first_valid] = np.nan
            num_cols[col] = arr
        else:
            obj_cols[col] = series.to_numpy()
    return _StaticTable(dates_arr, num_cols, obj_cols)


class MarketData:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        frequency: str = "daily",
        valuation: dict[str, pd.DataFrame] | None = None,
        dividend: dict[str, pd.DataFrame] | None = None,
        financial: dict[str, pd.DataFrame] | None = None,
        weekly_data: dict[str, pd.DataFrame] | None = None,
        monthly_data: dict[str, pd.DataFrame] | None = None,
    ):
        if not stock_data:
            raise ValueError("MarketData requires non-empty stock_data")

        self._frequency = frequency
        self._valuation = valuation or {}
        self._dividend = dividend or {}
        self._financial = financial or {}

        # valuation/financial 的预编译表(走 searchsorted + 数组下标快速查询)
        self._valuation_cache: dict[str, _StaticTable] = {
            sym: _build_static_table(df, date_col="date")
            for sym, df in self._valuation.items()
        }
        self._financial_cache: dict[str, _StaticTable] = {
            sym: _build_static_table(df, date_col="REPORT_DATE", ffill=False)
            for sym, df in self._financial.items()
        }
        # 仅含年报(REPORT_DATE 以 -12-31 结尾)的子表 → get_financial_annual 用
        # 银行股等季报累计 ROE 不年化、年中拉低 ROE,需要单独走年报口径
        self._financial_annual_cache: dict[str, _StaticTable] = {}
        for sym, df in self._financial.items():
            if df is None or df.empty or "REPORT_DATE" not in df.columns:
                continue
            mask = df["REPORT_DATE"].astype(str).str.endswith("-12-31")
            sub = df[mask]
            if sub.empty:
                continue
            self._financial_annual_cache[sym] = _build_static_table(
                sub, date_col="REPORT_DATE", ffill=False
            )

        # 按 symbol 缓存升序 daily DataFrame(stock_data 入参允许降序,统一规整)
        # 检测是否已带预算指标列(ma5 出现即视为预算路径,避免重复 compute)
        daily_cache: dict[str, pd.DataFrame] = {}
        for sym, df in stock_data.items():
            d = df.sort_values("date").reset_index(drop=True)
            if "ma5" not in d.columns:
                d = compute_indicators(d)
            daily_cache[sym] = d

        # weekly/monthly:优先用入参(data_cache 已预算);未提供时初始化空,
        # 由 _build_period_cache 在被请求时按需聚合(测试 / 单股回测路径)
        weekly_cache: dict[str, pd.DataFrame] = {}
        monthly_cache: dict[str, pd.DataFrame] = {}
        if weekly_data:
            for sym, df in weekly_data.items():
                w = df.sort_values("date").reset_index(drop=True)
                if "ma5" not in w.columns:
                    w = compute_indicators(w)
                weekly_cache[sym] = w
        if monthly_data:
            for sym, df in monthly_data.items():
                m = df.sort_values("date").reset_index(drop=True)
                if "ma5" not in m.columns:
                    m = compute_indicators(m)
                monthly_cache[sym] = m

        self._period_cache: dict[str, dict[str, pd.DataFrame]] = {
            "daily": daily_cache,
        }
        if weekly_cache:
            self._period_cache["weekly"] = weekly_cache
        if monthly_cache:
            self._period_cache["monthly"] = monthly_cache

        # date 数组缓存(searchsorted)
        self._date_arrays: dict[str, dict[str, np.ndarray]] = {
            "daily": {sym: df["date"].to_numpy() for sym, df in daily_cache.items()}
        }
        for period in ("weekly", "monthly"):
            if period in self._period_cache:
                self._date_arrays[period] = {
                    sym: df["date"].to_numpy()
                    for sym, df in self._period_cache[period].items()
                }

        # OHLC 数组缓存(get_bar_at 热路径)
        self._ohlc_arrays: dict[str, dict[str, dict[str, np.ndarray]]] = {
            "daily": {sym: self._extract_ohlc(df) for sym, df in daily_cache.items()}
        }
        for period in ("weekly", "monthly"):
            if period in self._period_cache:
                self._ohlc_arrays[period] = {
                    sym: self._extract_ohlc(df)
                    for sym, df in self._period_cache[period].items()
                }

        # 指标列 numpy 数组缓存(get_indicator 走 O(1) 列下标)
        # 结构:_indicator_arrays[period][symbol][col_name] = np.ndarray
        self._indicator_arrays: dict[str, dict[str, dict[str, np.ndarray]]] = {}
        for period, syms_df in self._period_cache.items():
            self._indicator_arrays[period] = {}
            for sym, df in syms_df.items():
                self._indicator_arrays[period][sym] = self._extract_indicators(df)

        # 时间轴:取第一只股票全历史日历(参考股票),升序
        ref_sym = next(iter(daily_cache))
        self.dates: list[str] = daily_cache[ref_sym]["date"].tolist()

        # 向后兼容:若策略 frequency 为 weekly/monthly 但调用方未提供预算
        # weekly/monthly_data,启动时按需聚合一次(此前 MarketData 的固定行为)。
        if frequency in ("weekly", "monthly") and frequency not in self._period_cache:
            self._build_period_cache(frequency)

    # ---------- 内部 ----------

    @staticmethod
    def _extract_ohlc(df: pd.DataFrame) -> dict[str, np.ndarray]:
        """抽取 OHLC 四列为 numpy 数组(零拷贝 view,共享底层 buffer)。"""
        out = {
            "open": df["open"].to_numpy(),
            "high": df["high"].to_numpy(),
            "low": df["low"].to_numpy(),
            "close": df["close"].to_numpy(),
        }
        if "volume" in df.columns:
            out["volume"] = df["volume"].to_numpy()
        return out

    @staticmethod
    def _extract_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
        """抽取所有 indicators.compute_indicators 输出列为 numpy 数组缓存。"""
        # 标准列名集合,与 indicators.STANDARD_* 同步;不在的列直接跳过
        candidate_cols = (
            "ma5",
            "ma10",
            "ma20",
            "ma30",
            "ema12",
            "ema26",
            "macd_dif",
            "macd_dea",
            "macd_hist",
            "vol_ma5",
            "vol_ma10",
            "ret_1",
            "vol_20d",
        )
        out: dict[str, np.ndarray] = {}
        for col in candidate_cols:
            if col in df.columns:
                out[col] = df[col].to_numpy(dtype=float)
        return out

    def _build_period_cache(self, period: str) -> None:
        """聚合所有 symbol 的日线为 weekly/monthly,缓存升序(测试 fallback 路径)。"""
        if period == "daily" or period in self._period_cache:
            return
        agg_period = period
        cache: dict[str, pd.DataFrame] = {}
        for sym, df in self._period_cache["daily"].items():
            agg = aggregate_kline(df, period=agg_period)
            agg = agg.sort_values("date").reset_index(drop=True)
            cache[sym] = compute_indicators(agg)
        self._period_cache[period] = cache
        self._date_arrays[period] = {
            sym: df["date"].to_numpy() for sym, df in cache.items()
        }
        self._ohlc_arrays[period] = {
            sym: self._extract_ohlc(df) for sym, df in cache.items()
        }
        self._indicator_arrays[period] = {
            sym: self._extract_indicators(df) for sym, df in cache.items()
        }

    def _get_period_df(self, symbol: str, period: str) -> pd.DataFrame | None:
        if period not in self._period_cache:
            self._build_period_cache(period)
        return self._period_cache[period].get(symbol)

    def _resolve_idx(
        self, symbol: str, period: str, idx: int
    ) -> tuple[pd.DataFrame | None, int]:
        """把 daily 时间轴上的 ``idx`` 映射到 period DataFrame 的行号。

        - daily:用 symbol 自身 DataFrame,按 ``dates[idx]`` 反查最大 ``date <= 目标``
          的行(允许个股停牌/交易日不齐)
        - weekly/monthly:在聚合后的 DataFrame 中查找最近一根「截止日 <= 目标」的周/月线
        """
        if idx < 0 or idx >= len(self.dates):
            return None, -1
        df = self._get_period_df(symbol, period)
        if df is None or df.empty:
            return None, -1
        arr = self._date_arrays.get(period, {}).get(symbol)
        if arr is None or len(arr) == 0:
            return df, -1
        target_date = self.dates[idx]
        pos = int(np.searchsorted(arr, target_date, side="right")) - 1
        if pos < 0:
            return df, -1
        return df, pos

    # ---------- 公开 API ----------

    def get_price(
        self, symbol: str, period: str = "daily", idx: int | None = None
    ) -> dict | None:
        if idx is None:
            return None
        df, i = self._resolve_idx(symbol, period, idx)
        if df is None or i < 0:
            return None
        return df.iloc[i].to_dict()

    def get_bar_at(
        self, symbol: str, idx: int, period: str = "daily", strict: bool = True
    ) -> dict | None:
        """快速 OHLC 取值(engine._build_bar 热路径)。"""
        if idx < 0 or idx >= len(self.dates):
            return None
        if period not in self._period_cache:
            self._build_period_cache(period)
        arr = self._date_arrays.get(period, {}).get(symbol)
        if arr is None or len(arr) == 0:
            return None
        target = self.dates[idx]
        pos = int(np.searchsorted(arr, target, side="right")) - 1
        if pos < 0:
            return None
        bar_date = arr[pos]
        if strict and bar_date != target:
            return None
        ohlc = self._ohlc_arrays[period][symbol]
        bar = {
            "open": float(ohlc["open"][pos]),
            "high": float(ohlc["high"][pos]),
            "low": float(ohlc["low"][pos]),
            "close": float(ohlc["close"][pos]),
            "date": bar_date,
        }
        if "volume" in ohlc:
            bar["volume"] = float(ohlc["volume"][pos])
        return bar

    def get_history(
        self,
        symbol: str,
        n: int,
        period: str = "daily",
        idx: int | None = None,
    ) -> list[dict]:
        if idx is None or n <= 0:
            return []
        df, i = self._resolve_idx(symbol, period, idx)
        if df is None or i < 0:
            return []
        start = max(0, i - n + 1)
        end = i + 1
        return df.iloc[start:end].to_dict(orient="records")

    def get_valuation(self, symbol: str, date: str) -> dict | None:
        table = self._valuation_cache.get(symbol)
        if table is None or table.n == 0:
            return None
        pos = int(np.searchsorted(table.dates, date, side="right")) - 1
        if pos < 0:
            return None
        result: dict[str, Any] = {"date": table.dates[pos]}
        for col, arr in table.num_cols.items():
            v = arr[pos]
            result[col] = None if math.isnan(v) else float(v)
        for col, arr in table.obj_cols.items():
            v = arr[pos]
            result[col] = v
        return result

    def get_dividend(self, symbol: str, date: str) -> pd.DataFrame | None:
        df = self._dividend.get(symbol)
        if df is None or df.empty:
            return None
        return df

    def get_financial(self, symbol: str, date: str) -> dict | None:
        return self._lookup_financial_table(self._financial_cache, symbol, date)

    def get_financial_annual(self, symbol: str, date: str) -> dict | None:
        """仅返回 REPORT_DATE 以 -12-31 结尾的最近一份年报。

        语义:截至 ``date``,回滚到 <= date 的最新年报。年中查询会回退到上一年报。
        ``filter_by_roe`` 等基于「年化 ROE」的策略 helper 应走此入口,避免季度累计值。
        """
        return self._lookup_financial_table(self._financial_annual_cache, symbol, date)

    def _lookup_financial_table(
        self, cache: dict[str, _StaticTable], symbol: str, date: str
    ) -> dict | None:
        table = cache.get(symbol)
        if table is None or table.n == 0:
            return None
        pos = int(np.searchsorted(table.dates, date, side="right")) - 1
        if pos < 0:
            return None
        result: dict[str, Any] = {"REPORT_DATE": table.dates[pos]}
        for col, arr in table.num_cols.items():
            v = arr[pos]
            result[col] = None if math.isnan(v) else float(v)
        for col, arr in table.obj_cols.items():
            result[col] = arr[pos]
        return result

    # ---------- 指标查表(get_indicator)----------

    def get_indicator(
        self,
        name: str,
        symbol: str,
        idx: int | None = None,
        period: str = "daily",
        **kwargs: Any,
    ) -> float | None:
        """O(1) 查预算指标。命中标准列返回 float / None,否则返回 None 让上层 fallback。

        - name 解析:见 indicators.resolve_indicator_column
        - 时间映射:与 _resolve_idx 一致(period 指定周期,idx 是 daily 轴上的位置)
        - NaN(数据不足窗口期)返回 None,业务方按"无效"处理
        """
        if idx is None:
            return None
        col = resolve_indicator_column(name, **kwargs)
        if col is None:
            return None
        # 触发 weekly/monthly 懒聚合(若需要)
        if period not in self._period_cache:
            self._build_period_cache(period)
        period_arrs = self._indicator_arrays.get(period, {})
        sym_arrs = period_arrs.get(symbol)
        if sym_arrs is None:
            return None
        arr = sym_arrs.get(col)
        if arr is None:
            return None
        # 把 daily idx 映射到 period 上的行号
        date_arr = self._date_arrays.get(period, {}).get(symbol)
        if date_arr is None or len(date_arr) == 0:
            return None
        if idx < 0 or idx >= len(self.dates):
            return None
        target = self.dates[idx]
        pos = int(np.searchsorted(date_arr, target, side="right")) - 1
        if pos < 0 or pos >= len(arr):
            return None
        v = arr[pos]
        if isinstance(v, float) and math.isnan(v):
            return None
        return float(v)

    def indicator(
        self, name: str, symbol: str, idx: int | None = None, **kwargs: Any
    ) -> Any:
        """旧接口别名 — 透传到 get_indicator,保持向后兼容。"""
        return self.get_indicator(name, symbol, idx=idx, **kwargs)
