"""MarketData 适配器(Phase 3.2)。

被新 ``BacktestEngine`` (T3.3) 直接构造,封装 stock_data dict + 周/月聚合缓存,
并对外暴露 ``Context`` (T3.1) 所需的最小数据访问 API。

设计要点(plan §3.2):
- 输入:``{symbol: pd.DataFrame(daily)}`` + ``frequency``,可选 valuation/dividend/financial 字典
- ``dates``:以 stock_data 中第一只股票的日历为参考,升序日期列表
- 启动时按 ``frequency`` 预聚合 weekly→W-FRI / monthly→M(daily 时不聚合);
  其它 period 在被请求时按需懒计算并缓存,避免重复
- 持仓相关 API 由 Broker 提供,本类不负责
- valuation / dividend / financial:对应 dict 入参,**默认 None 时返回 None**
  (Phase 4 Layer B 之后会切换到 DuckDB)
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from services.stock_data import aggregate_kline


class MarketData:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        frequency: str = "daily",
        valuation: dict[str, pd.DataFrame] | None = None,
        dividend: dict[str, pd.DataFrame] | None = None,
        financial: dict[str, pd.DataFrame] | None = None,
    ):
        if not stock_data:
            raise ValueError("MarketData requires non-empty stock_data")

        self._frequency = frequency
        self._valuation = valuation or {}
        self._dividend = dividend or {}
        self._financial = financial or {}

        # 按 symbol 缓存升序 daily DataFrame(stock_data 入参允许降序,统一规整)
        daily_cache: dict[str, pd.DataFrame] = {
            sym: df.sort_values("date").reset_index(drop=True)
            for sym, df in stock_data.items()
        }
        self._period_cache: dict[str, dict[str, pd.DataFrame]] = {"daily": daily_cache}

        # 时间轴:取第一只股票的日历(参考股票),升序
        ref_sym = next(iter(daily_cache))
        self.dates: list[str] = daily_cache[ref_sym]["date"].tolist()

        # 启动时按 frequency 预聚合(daily 不需要)
        if frequency in ("weekly", "monthly"):
            self._build_period_cache(frequency)

    # ---------- 内部 ----------

    def _build_period_cache(self, period: str) -> None:
        """聚合所有 symbol 的日线为 weekly/monthly,缓存升序。"""
        if period == "daily":
            return
        agg_period = period  # aggregate_kline 接受 "weekly" / "monthly"
        cache: dict[str, pd.DataFrame] = {}
        for sym, df in self._period_cache["daily"].items():
            agg = aggregate_kline(df, period=agg_period)
            cache[sym] = agg.sort_values("date").reset_index(drop=True)
        self._period_cache[period] = cache

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
        target_date = self.dates[idx]
        mask = df["date"] <= target_date
        if not mask.any():
            return df, -1
        return df, int(mask.values.nonzero()[0][-1])

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
        df = self._valuation.get(symbol)
        if df is None or df.empty:
            return None
        dates = df["date"]
        # 容忍 datetime 列
        if len(dates) > 0 and not isinstance(dates.iloc[0], str):
            dates = dates.astype(str)
        mask = dates <= date
        if not mask.any():
            return None
        row = df.loc[mask].iloc[-1]
        result: dict[str, Any] = {}
        for col in df.columns:
            if col == "date":
                result[col] = row[col]
                continue
            val = row[col]
            if isinstance(val, float) and math.isnan(val):
                # 在已过滤窗口内向上回填:取 col 列上最近一个非空值
                sub_mask = mask & df[col].notna()
                result[col] = (
                    float(df.loc[sub_mask, col].iloc[-1]) if sub_mask.any() else None
                )
            else:
                result[col] = float(val) if val is not None else None
        return result

    def get_dividend(self, symbol: str, date: str) -> pd.DataFrame | None:
        # 与旧 ScreenerContext 保持一致:返回完整 DataFrame(策略自行按 date 过滤)
        df = self._dividend.get(symbol)
        if df is None or df.empty:
            return None
        return df

    def get_financial(self, symbol: str, date: str) -> dict | None:
        df = self._financial.get(symbol)
        if df is None or df.empty:
            return None
        dates = df["报告期"]
        if len(dates) > 0 and not isinstance(dates.iloc[0], str):
            dates = dates.astype(str)
        mask = dates <= date
        if not mask.any():
            return None
        row = df.loc[mask].iloc[-1]
        result: dict[str, Any] = {}
        for col in df.columns:
            if col in ("报告期", "股票代码", "股票简称", "所处行业", "最新公告日期"):
                result[col] = row[col]
                continue
            val = row[col]
            if isinstance(val, float) and math.isnan(val):
                result[col] = None
            else:
                result[col] = float(val) if isinstance(val, (int, float)) else val
        return result

    def indicator(
        self, name: str, symbol: str, idx: int | None = None, **kwargs: Any
    ) -> Any:
        """指标计算入口(Phase 3.2 占位实现,Phase 4 接 DuckDB / 预算缓存)。

        当前未启用预算缓存;调用方(Context)在 Phase 3 阶段尚未对此做硬依赖,
        T3.3 Engine 与策略测试均通过 mock 替代。返回 None 以保持接口可调用。
        """
        return None
