"""全市场回测数据缓存(方案 A:K 线 + 估值 + 分红 + 财务全部常驻内存)。

设计:
- 按 market("A"/"HK"/"US")组织 entry,每个 entry 含四份完整数据 +
  预聚合 weekly/monthly + 预算标准指标(ma/ema/macd/vol_ma/ret_1/vol_20d)
- HK/US 暂无估值/分红/财务数据,只缓存 K 线
- 加载在后台线程执行,通过 _progress 暴露进度
- backtest 时通过 get_market() 拿 bundle,按 symbols 切片(slice_bundle 返回
  SlicedBundle:全历史 daily/weekly/monthly + iter_start/iter_end)。日期范围
  仅用于决定迭代窗口,**不再裁剪 daily 数据**,这样月线 MA20 等长窗口指标
  在 1y lookback 下仍然有效(2026-05-22 架构升级,见 AGENTS.md / 决策 #9)。
- 数据更新后调用 invalidate(market) 失效缓存(scheduler 06:00 完成自动重建)

线程安全:
- _cache 写入用 _lock 保护
- 读取(get_market/get_status)允许并发,Python dict 原子读 + 不可变 bundle 字段
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from services.backtest.indicators import compute_indicators
from services.duckdb_store import get_store
from services.stock_data import aggregate_kline

logger = logging.getLogger(__name__)


SUPPORTED_MARKETS = ("A", "HK", "US")


@dataclass
class MarketBundle:
    market: str
    stock_data: dict[str, pd.DataFrame]
    weekly_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    monthly_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    valuation_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    dividend_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    financial_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    # 现金流保守策略 v1(2026-05-27):balance/cashflow 用于 Layer 2 否决项
    # (商誉占比 / 净现金转负 / FCF 持续为负)
    balance_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    cashflow_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    # L1.3 信誉评级(2026-05-27):income 用于营收 CV + 利润调整幅度
    income_data: dict[str, pd.DataFrame] = field(default_factory=dict)
    loaded_at: float = 0.0  # epoch seconds

    @property
    def symbols_count(self) -> int:
        return len(self.stock_data)

    @property
    def last_date(self) -> str | None:
        """数据截止日(YYYY-MM-DD):取若干样本股的最后一行 date 取 max。

        cache 加载时 df 已按 date 升序(_aggregate_and_compute line 205),
        最后一行是最新交易日。同市场各股理论应对齐到同一交易日,但保险起见
        取多只 sample 取 max,避免某只股票数据缺失影响判定。
        """
        if not self.stock_data:
            return None
        latest = None
        for i, df in enumerate(self.stock_data.values()):
            if i >= 20:  # 采样上限
                break
            if df is None or df.empty or "date" not in df.columns:
                continue
            d = df["date"].iloc[-1]
            d_str = str(d)[:10]
            if latest is None or d_str > latest:
                latest = d_str
        return latest


@dataclass
class SlicedBundle:
    """slice_bundle 的返回值。daily/weekly/monthly 均保留 symbols 子集的全历史,
    iter_start_idx / iter_end_idx 限定回测主循环的迭代窗口(基于参考股 daily 日历)。
    """

    stock_data: dict[str, pd.DataFrame]
    weekly_data: dict[str, pd.DataFrame]
    monthly_data: dict[str, pd.DataFrame]
    valuation_data: dict[str, pd.DataFrame]
    dividend_data: dict[str, pd.DataFrame]
    financial_data: dict[str, pd.DataFrame]
    balance_data: dict[str, pd.DataFrame]
    cashflow_data: dict[str, pd.DataFrame]
    income_data: dict[str, pd.DataFrame]
    iter_start_idx: int
    iter_end_idx: int  # inclusive


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
    """估值序列(English schema:date / peTTM / pbMRQ / psTTM / pcfNcfTTM)。"""
    try:
        out = get_store().query_valuation_bulk(market, symbols)
        logger.info(
            "_load_valuation: market=%s in=%d out=%d", market, len(symbols), len(out)
        )
        return out
    except Exception as e:
        logger.exception("_load_valuation failed: %s", e)
        return {}


def _load_dividend(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """分红事件(English schema:date / cash_dividend / stocks_ps / record_date / pay_date)。"""
    try:
        out = get_store().query_dividend_bulk(market, symbols)
        logger.info(
            "_load_dividend: market=%s in=%d out=%d", market, len(symbols), len(out)
        )
        return out
    except Exception as e:
        logger.exception("_load_dividend failed: %s", e)
        return {}


def _load_financial(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """财务指标(English schema:REPORT_DATE / ROEJQ / EPSJB / BPS / TOTAL_SHARE / ...)。"""
    try:
        out = get_store().query_financial_bulk(market, symbols, fin_type="indicator")
        logger.info(
            "_load_financial: market=%s in=%d out=%d", market, len(symbols), len(out)
        )
        return out
    except Exception as e:
        logger.exception("_load_financial failed: %s", e)
        return {}


def _load_balance(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """资产负债表(English schema:REPORT_DATE / MONETARYFUNDS / GOODWILL /
    TOTAL_ASSETS / TOTAL_LIABILITIES / TOTAL_PARENT_EQUITY / ...)。"""
    try:
        out = get_store().query_financial_bulk(market, symbols, fin_type="balance")
        logger.info(
            "_load_balance: market=%s in=%d out=%d", market, len(symbols), len(out)
        )
        return out
    except Exception as e:
        logger.exception("_load_balance failed: %s", e)
        return {}


def _load_cashflow(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """现金流量表(English schema:REPORT_DATE / NETCASH_OPERATE /
    CONSTRUCT_LONG_ASSET / NETCASH_INVEST / NETCASH_FINANCE / ...)。"""
    try:
        out = get_store().query_financial_bulk(market, symbols, fin_type="cashflow")
        logger.info(
            "_load_cashflow: market=%s in=%d out=%d", market, len(symbols), len(out)
        )
        return out
    except Exception as e:
        logger.exception("_load_cashflow failed: %s", e)
        return {}


def _load_income(market: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """利润表(English schema:REPORT_DATE / TOTAL_OPERATE_INCOME / PARENT_NETPROFIT /
    DEDUCT_PARENT_NETPROFIT / ...)。用于 L1.3 信誉评级(营收 CV + 利润调整幅度)。"""
    try:
        out = get_store().query_financial_bulk(market, symbols, fin_type="income")
        logger.info(
            "_load_income: market=%s in=%d out=%d", market, len(symbols), len(out)
        )
        return out
    except Exception as e:
        logger.exception("_load_income failed: %s", e)
        return {}


def _aggregate_and_compute(
    daily: dict[str, pd.DataFrame], progress: LoadProgress
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """对每只股票预聚合 weekly/monthly 并预算指标。

    daily 入参在调用前已经过 ``compute_indicators``;weekly/monthly 由 daily
    经 ``aggregate_kline`` 聚合后再调一次 compute_indicators。
    """
    weekly: dict[str, pd.DataFrame] = {}
    monthly: dict[str, pd.DataFrame] = {}
    daily_with_indicators: dict[str, pd.DataFrame] = {}

    total = len(daily)
    progress.total = total
    progress.current = 0
    progress.phase = "预算指标(daily/weekly/monthly)..."

    for sym, df in daily.items():
        # daily:升序后追加指标列
        d = df.sort_values("date").reset_index(drop=True)
        daily_with_indicators[sym] = compute_indicators(d)

        # weekly/monthly:从原始 daily(无指标列)聚合,再追加指标列。
        # aggregate_kline 用 OHLCV 聚合,指标列对其无意义,所以用未加指标的 d。
        w = aggregate_kline(d, period="weekly")
        if w is not None and not w.empty:
            w = w.sort_values("date").reset_index(drop=True)
            weekly[sym] = compute_indicators(w)

        m = aggregate_kline(d, period="monthly")
        if m is not None and not m.empty:
            m = m.sort_values("date").reset_index(drop=True)
            monthly[sym] = compute_indicators(m)

        progress.current += 1

    return daily_with_indicators, weekly, monthly


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
    logger.info("data_cache: 开始加载 market=%s 全市场数据...", market)

    try:
        t0 = time.time()
        stock_data_raw = _load_stock_data_full(market)
        symbols = list(stock_data_raw.keys())
        p.current = len(symbols)
        p.total = len(symbols)
        p.phase = f"K 线加载完成({len(symbols)} 只),聚合 weekly/monthly + 预算指标..."
        logger.info(
            "data_cache: [%s] K 线加载完成 — symbols=%d, 耗时 %.1fs",
            market,
            len(symbols),
            time.time() - t0,
        )

        # 预聚合 + 预算指标(daily/weekly/monthly 三套)— 是本架构升级的关键
        # 一次性付出 30-60s 成本,后续回测/雷达全部 O(1) 查列
        t1 = time.time()
        stock_data, weekly_data, monthly_data = _aggregate_and_compute(
            stock_data_raw, p
        )
        logger.info(
            "data_cache: [%s] 指标预算完成 — daily=%d / weekly=%d / monthly=%d, 耗时 %.1fs",
            market,
            len(stock_data),
            len(weekly_data),
            len(monthly_data),
            time.time() - t1,
        )

        p.phase = f"指标预算完成,加载估值/分红/财务({len(symbols)} 只)..."
        # DuckDB 单连接不支持并发查询(会触发 "result closed"),串行执行。
        t2 = time.time()
        valuation_data = _load_valuation(market, symbols)
        dividend_data = _load_dividend(market, symbols)
        financial_data = _load_financial(market, symbols)
        balance_data = _load_balance(market, symbols)
        cashflow_data = _load_cashflow(market, symbols)
        income_data = _load_income(market, symbols)
        logger.info(
            "data_cache: [%s] 估值/分红/财务/资产负债/现金流/利润表加载完成 — "
            "valuation=%d / dividend=%d / financial=%d / balance=%d / cashflow=%d / income=%d, 耗时 %.1fs",
            market,
            len(valuation_data),
            len(dividend_data),
            len(financial_data),
            len(balance_data),
            len(cashflow_data),
            len(income_data),
            time.time() - t2,
        )

        bundle = MarketBundle(
            market=market,
            stock_data=stock_data,
            weekly_data=weekly_data,
            monthly_data=monthly_data,
            valuation_data=valuation_data,
            dividend_data=dividend_data,
            financial_data=financial_data,
            balance_data=balance_data,
            cashflow_data=cashflow_data,
            income_data=income_data,
            loaded_at=time.time(),
        )
        with _lock:
            _cache[market] = bundle
        p.status = "loaded"
        p.phase = (
            f"完成:K 线 {len(stock_data)} / 周 {len(weekly_data)} / "
            f"月 {len(monthly_data)} / 估值 {len(valuation_data)} / "
            f"分红 {len(dividend_data)} / 财务 {len(financial_data)} / "
            f"资产负债 {len(balance_data)} / 现金流 {len(cashflow_data)} / 利润表 {len(income_data)}"
        )
        p.finished_at = time.time()
        logger.info(
            "data_cache: %s loaded in %.1fs (stocks=%d, weekly=%d, monthly=%d)",
            market,
            p.finished_at - p.started_at,
            len(stock_data),
            len(weekly_data),
            len(monthly_data),
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
        "balance_count": len(bundle.balance_data) if bundle else 0,
        "cashflow_count": len(bundle.cashflow_data) if bundle else 0,
        "income_count": len(bundle.income_data) if bundle else 0,
        "loaded_at": bundle.loaded_at if bundle else 0.0,
        "last_date": bundle.last_date if bundle else None,
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
) -> SlicedBundle:
    """从 bundle 切出 symbols 子集 + 决定迭代窗口。

    ⚠️ 关键变化(2026-05-22):**daily/weekly/monthly 数据始终保留全历史**,
    start_date/end_date 仅用于计算 iter_start_idx/iter_end_idx。这样 1y lookback
    回测 + 月线 MA20 长窗口指标也能正确运转(否则 daily 切到 1y 后聚合月线只剩 12 根)。

    - symbols=None → 全市场子集
    - start/end=None → iter window 默认覆盖参考股全历史
    - 参考股 = 子集第一只(用作时间轴,与 MarketData.dates 一致)
    """
    target_syms = set(symbols) if symbols else None

    def _subset(d: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        if target_syms is None:
            return dict(d)
        return {s: d[s] for s in target_syms if s in d}

    stock = _subset(bundle.stock_data)
    weekly = _subset(bundle.weekly_data)
    monthly = _subset(bundle.monthly_data)
    val = _subset(bundle.valuation_data)
    div = _subset(bundle.dividend_data)
    fin = _subset(bundle.financial_data)
    bal = _subset(bundle.balance_data)
    cf = _subset(bundle.cashflow_data)
    inc = _subset(bundle.income_data)

    if not stock:
        return SlicedBundle(
            stock_data={},
            weekly_data={},
            monthly_data={},
            valuation_data=val,
            dividend_data=div,
            financial_data=fin,
            balance_data=bal,
            cashflow_data=cf,
            income_data=inc,
            iter_start_idx=0,
            iter_end_idx=-1,
        )

    # 用参考股的全历史 date 列作为迭代时间轴
    ref_sym = next(iter(stock))
    ref_dates = stock[ref_sym]["date"].to_numpy()
    n = len(ref_dates)

    if n == 0:
        iter_start = 0
        iter_end = -1
    else:
        # start_date / end_date 都按 "≥/≤" 边界对齐到最近的存在日历日
        if start_date:
            iter_start = int(np.searchsorted(ref_dates, start_date, side="left"))
            iter_start = min(iter_start, n - 1)
        else:
            iter_start = 0
        if end_date:
            # searchsorted right - 1 = 最大 ≤ end_date 的索引
            iter_end = int(np.searchsorted(ref_dates, end_date, side="right")) - 1
            iter_end = max(iter_end, 0)
        else:
            iter_end = n - 1

    return SlicedBundle(
        stock_data=stock,
        weekly_data=weekly,
        monthly_data=monthly,
        valuation_data=val,
        dividend_data=div,
        financial_data=fin,
        balance_data=bal,
        cashflow_data=cf,
        income_data=inc,
        iter_start_idx=iter_start,
        iter_end_idx=iter_end,
    )
