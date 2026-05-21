"""全市场回测数据缓存(方案 A:K 线 + 估值 + 分红 + 财务全部常驻内存)。

设计:
- 按 market("A"/"HK"/"US")组织 entry,每个 entry 含四份完整数据
- HK/US 暂无估值/分红/财务数据,只缓存 K 线
- 加载在后台线程执行,通过 _progress 暴露进度
- backtest 时通过 get_market() 拿 bundle,按 start_date/end_date/symbols 切片
- 数据更新后调用 invalidate(market) 失效缓存(暂不接 scheduler,手动触发)

线程安全:
- _cache 写入用 _lock 保护
- 读取(get_market/get_status)允许并发,Python dict 原子读 + 不可变 bundle 字段
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from services.duckdb_store import get_store

logger = logging.getLogger(__name__)


SUPPORTED_MARKETS = ("A", "HK", "US")


@dataclass
class MarketBundle:
    market: str
    stock_data: dict[str, pd.DataFrame]
    valuation_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    dividend_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    financial_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    loaded_at: float = 0.0  # epoch seconds

    @property
    def symbols_count(self) -> int:
        return len(self.stock_data)


@dataclass
class LoadProgress:
    status: str = "idle"  # idle / loading / loaded / failed
    current: int = 0
    total: int = 0
    phase: str = ""
    error: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0


_cache: dict[str, MarketBundle] = {}
_progress: dict[str, LoadProgress] = {m: LoadProgress() for m in SUPPORTED_MARKETS}
_lock = threading.Lock()


# ---------- 内部加载逻辑 ----------


def _load_stock_data_full(market: str) -> dict[str, pd.DataFrame]:
    """全市场 + 全历史拉取前复权 K 线。"""
    store = get_store()
    return store.query_qfq_kline_bulk(market=market, symbols=None, start=None, end=None)


def _load_valuation(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """估值序列(English schema:date / peTTM / pbMRQ / psTTM / pcfNcfTTM)。
    源:DuckDB v_{market}_daily 的估值列(A 股 BaoStock 自带)。
    """
    return get_store().query_valuation_bulk(market, symbols)


def _load_dividend(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """分红事件(English schema:date / cash_dividend / stocks_ps / record_date / pay_date)。
    源:DuckDB v_{market}_dividend(A 股 BaoStock,HK/US 从 cashflow.DIVIDENDS_PAID 派生)。
    """
    return get_store().query_dividend_bulk(market, symbols)


def _load_financial(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """财务指标(English schema:REPORT_DATE / ROEJQ / EPSJB / BPS / TOTAL_SHARE / ...)。
    源:DuckDB v_{market}_indicator(EastMoney)。
    """
    return get_store().query_financial_bulk(market, symbols, fin_type="indicator")


def _load_market_blocking(market: str) -> MarketBundle:
    """同步加载指定市场全量数据,期间更新 _progress[market]。"""
    p = _progress[market]
    p.status = "loading"
    p.started_at = time.time()
    p.finished_at = 0.0
    p.error = None
    p.phase = "加载 K 线..."
    p.current = 0
    p.total = 0

    try:
        stock_data = _load_stock_data_full(market)
        symbols = list(stock_data.keys())
        p.current = len(symbols)
        p.total = len(symbols)
        p.phase = f"K 线加载完成({len(symbols)} 只),加载估值/分红/财务..."

        valuation_data: dict[str, pd.DataFrame] = {}
        dividend_data: dict[str, pd.DataFrame] = {}
        financial_data: dict[str, pd.DataFrame] = {}

        # 三市场都通过 DuckDB 视图加载;HK/US 估值视图缺失会返回空 dict(防御)
        with ThreadPoolExecutor(max_workers=3) as pool:
            fv = pool.submit(_load_valuation, market, symbols)
            fd = pool.submit(_load_dividend, market, symbols)
            ff = pool.submit(_load_financial, market, symbols)
            valuation_data = fv.result()
            dividend_data = fd.result()
            financial_data = ff.result()

        bundle = MarketBundle(
            market=market,
            stock_data=stock_data,
            valuation_data=valuation_data,
            dividend_data=dividend_data,
            financial_data=financial_data,
            loaded_at=time.time(),
        )
        with _lock:
            _cache[market] = bundle
        p.status = "loaded"
        p.phase = (
            f"完成:K 线 {len(stock_data)} 只 / 估值 {len(valuation_data)} / "
            f"分红 {len(dividend_data)} / 财务 {len(financial_data)}"
        )
        p.finished_at = time.time()
        logger.info(
            "data_cache: %s loaded in %.1fs (stocks=%d)",
            market,
            p.finished_at - p.started_at,
            len(stock_data),
        )
        return bundle
    except Exception as e:
        p.status = "failed"
        p.error = str(e)
        p.finished_at = time.time()
        logger.exception("data_cache load failed: market=%s", market)
        raise


# ---------- 公开 API ----------


def load_market_async(market: str) -> dict:
    """异步触发加载。已在加载中或已加载会原地返回当前状态(不重入)。"""
    market = market.upper()
    if market not in SUPPORTED_MARKETS:
        raise ValueError(f"Unsupported market: {market}")

    p = _progress[market]
    if p.status == "loading":
        return _status_dict(market)

    def _run():
        try:
            _load_market_blocking(market)
        except Exception:
            pass  # 错误已记录到 _progress

    threading.Thread(target=_run, daemon=True, name=f"data_cache_load_{market}").start()
    # 立即标记 loading 状态(避免前端轮询窗口期看到 idle)
    p.status = "loading"
    p.phase = "排队中..."
    p.started_at = time.time()
    p.finished_at = 0.0
    p.error = None
    return _status_dict(market)


def get_market(market: str) -> MarketBundle | None:
    return _cache.get(market.upper())


def invalidate(market: str | None = None) -> None:
    """清除缓存。market=None 清全部。"""
    with _lock:
        if market is None:
            _cache.clear()
            for m in SUPPORTED_MARKETS:
                _progress[m] = LoadProgress()
        else:
            m = market.upper()
            _cache.pop(m, None)
            _progress[m] = LoadProgress()


def _status_dict(market: str) -> dict:
    p = _progress[market]
    bundle = _cache.get(market)
    return {
        "market": market,
        "status": p.status,
        "loaded": bundle is not None,
        "symbols": bundle.symbols_count if bundle else 0,
        "valuation_count": len(bundle.valuation_data) if bundle else 0,
        "dividend_count": len(bundle.dividend_data) if bundle else 0,
        "financial_count": len(bundle.financial_data) if bundle else 0,
        "loaded_at": bundle.loaded_at if bundle else 0.0,
        "progress": {
            "current": p.current,
            "total": p.total,
            "phase": p.phase,
        },
        "error": p.error,
        "elapsed": (
            (p.finished_at or time.time()) - p.started_at if p.started_at else 0.0
        ),
    }


def get_status_all() -> dict:
    return {m: _status_dict(m) for m in SUPPORTED_MARKETS}


def slice_bundle(
    bundle: MarketBundle,
    symbols: list[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
]:
    """从 bundle 切出回测所需的子集(浅切片,不复制底层 buffer)。

    - symbols=None → 全市场
    - start/end=None → 不限日期
    """
    target_syms = set(symbols) if symbols else None

    def _subset(d: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        if target_syms is None:
            return dict(d)
        return {s: d[s] for s in target_syms if s in d}

    stock = _subset(bundle.stock_data)
    val = _subset(bundle.valuation_data)
    div = _subset(bundle.dividend_data)
    fin = _subset(bundle.financial_data)

    if start_date or end_date:
        # 只切 K 线 — engine 用 stock_data 第一只股票的 date 列作为时间轴,
        # 必须按 [start, end] 缩窄,否则回测会跑全历史。
        # 估值/分红/财务都是 lookup 模式(按 current_date 取最近一根),全量更安全
        # 也跟旧 router 行为一致(_load_valuation/dividend/financial 均不按日期过滤)。
        def _slice_kline(df: pd.DataFrame) -> pd.DataFrame:
            mask = pd.Series(True, index=df.index)
            if start_date:
                mask &= df["date"] >= start_date
            if end_date:
                mask &= df["date"] <= end_date
            return df.loc[mask].reset_index(drop=True) if not mask.all() else df

        stock = {s: _slice_kline(df) for s, df in stock.items()}

    return stock, val, div, fin
