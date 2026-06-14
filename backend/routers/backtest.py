"""回测 API(Phase 6.2 适配单一 Strategy 模型)。

旧多策略 pipeline + TraderStrategy/ScreenerStrategy 区分已废弃。现仅接受单一
Strategy class — 前端仍以 pipeline=[item] 形式提交,后端取首项实例化为 Strategy。
"""

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from config import DEPLOYED_STRATEGY_DIR, LOG_DIR
from services.api_utils import safe_json
from services.backtest import data_cache
from services.backtest.engine import BacktestEngine
from services.backtest.market_filter import apply_market_filter, resolve_data_market
from services.backtest.strategy_loader import load_strategy_from_file, scan_strategies
from services.backtest.task_manager import task_manager
from services.market_data.stock_index import get_name as get_stock_name
from services.backtest.strategy_base import Strategy


router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/strategies")
def api_list_strategies():
    # 只列已发布策略(strategies/deployed/);在研策略在 strategies/experiments/,不暴露给 UI
    if not DEPLOYED_STRATEGY_DIR.exists():
        return []
    return scan_strategies(DEPLOYED_STRATEGY_DIR)


@router.post("/run")
def api_run_backtest(body: dict = Body(...)):
    """运行回测。

    Phase 5 新格式(扁平,推荐):
        {strategy_class, filepath, params?, frequency_override?,
         start_date, end_date, symbols?, market?}

    遗留格式(向后兼容):
        {pipeline: [{filepath, class_name}], param_overrides: {ClassName: {...}}, ...}
    """
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    target_symbols = body.get("symbols")
    # market = 展示侧标识(可能含虚拟市场 HK_CONNECT);data_market = 物理数据市场
    market = (body.get("market") or "A").upper()
    data_market = resolve_data_market(market)
    # HK_CONNECT 时把 symbols 收敛到港股通成分股交集
    target_symbols = apply_market_filter(market, target_symbols)

    # 解析 strategy_class / filepath / overrides:支持新旧两种 payload
    if "strategy_class" in body:
        # 新格式(扁平)
        class_name = body["strategy_class"]
        filepath_str = body.get("filepath")
        if not filepath_str:
            raise HTTPException(status_code=400, detail="filepath is required")
        filepath = Path(filepath_str)
        overrides = body.get("params") or {}
    else:
        # 旧格式(pipeline 数组)
        pipeline = body.get("pipeline", [])
        if not pipeline:
            raise HTTPException(status_code=400, detail="Pipeline cannot be empty")
        item = pipeline[0]
        filepath = Path(item["filepath"])
        class_name = item["class_name"]
        param_overrides = body.get("param_overrides", {})
        overrides = param_overrides.get(class_name, {})

    classes = load_strategy_from_file(filepath)
    cls = next((c for c in classes if c.__name__ == class_name), None)
    if cls is None:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy class {class_name} not found in {filepath}",
        )
    strategy: Strategy = cls(param_overrides=overrides)

    # 扁平 pipeline_info: {strategy_class, params}(由 task_manager 内部构造)
    defaults = {k: v["default"] for k, v in getattr(cls, "params", {}).items()}
    merged_params = {**defaults, **overrides}
    # 持久化策略 intrinsic frequency / 中文 name,供前端结果头部 / 历史列表显示
    intrinsic_frequency = getattr(cls, "frequency", None)
    intrinsic_name = getattr(cls, "name", None) or class_name
    task_id = task_manager.create_task(
        task_type="backtest",
        strategy_class=class_name,
        strategy_name=intrinsic_name,
        params=merged_params,
        frequency=intrinsic_frequency,
        symbols=target_symbols,
        market=market,
        start_date=start_date,
        end_date=end_date,
    )

    def on_progress(current, total, phase=""):
        task_manager.update_progress(task_id, current, total, phase)

    def run_task():
        try:
            # 数据必须事先通过 /api/backtest/cache/load 显式加载,
            # 这里只做内存切片,不走任何 IO。
            bundle = data_cache.get_market(data_market)
            if bundle is None:
                raise RuntimeError(
                    f"{data_market} 市场数据未加载,请先在「策略回测」页点击「加载数据」"
                )
            task_manager.update_progress(task_id, 0, 0, "切片数据中...")
            sliced = data_cache.slice_bundle(
                bundle, target_symbols, start_date, end_date
            )
            if not sliced.stock_data:
                raise RuntimeError("切片后无可用 K 线数据,检查日期范围/股票代码")
            task_manager.update_progress(
                task_id,
                len(sliced.stock_data),
                len(sliced.stock_data),
                f"数据就绪 ({len(sliced.stock_data)} 只)",
            )
            # 决策日志目录:每个 task 独立子目录,与 task_manager 内部默认路径一致
            task_log_dir = LOG_DIR / "backtest" / task_id
            engine = BacktestEngine(
                strategy=strategy,
                stock_data=sliced.stock_data,
                valuation_data=sliced.valuation_data,
                dividend_data=sliced.dividend_data,
                financial_data=sliced.financial_data,
                balance_data=sliced.balance_data,
                cashflow_data=sliced.cashflow_data,
                income_data=sliced.income_data,
                weekly_data=sliced.weekly_data,
                monthly_data=sliced.monthly_data,
                iter_start=sliced.iter_start_idx,
                iter_end=sliced.iter_end_idx,
                on_progress=lambda cur, total: on_progress(cur, total, "回测中..."),
                log_dir=task_log_dir,
            )
            result = engine.run()
            result = safe_json(result)
            task_manager.complete_task(task_id, result)
        except Exception as e:
            task_manager.fail_task(task_id, str(e))

    t = threading.Thread(target=run_task, daemon=True)
    t.start()
    return {"task_id": task_id, "status": "running"}


@router.get("/status/{task_id}")
def api_backtest_status(task_id: str):
    status = task_manager.get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@router.get("/result/{task_id}")
def api_backtest_result(task_id: str):
    result = task_manager.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.get("/tasks")
def api_list_tasks(show_deleted: bool = False):
    return task_manager.list_tasks(show_deleted=show_deleted)


@router.delete("/tasks/{task_id}")
def api_delete_task(task_id: str):
    task_manager.delete_task(task_id)
    return {"ok": True}


# ---------- 策略雷达扫描(选股回测,无 trader)----------

_LOOKBACK_DAYS = {
    "yesterday": 0,
    "1m": 30,
    "6m": 182,
    "1y": 365,
    "3y": 365 * 3,
    "5y": 365 * 5,
}


def _resolve_scan_dates(bundle, lookback: str) -> tuple[str, str]:
    """从 bundle 推 end_date(数据最新日)+ 按 lookback 推 start_date。"""
    latest = ""
    for df in bundle.stock_data.values():
        if df is not None and not df.empty:
            d = str(df["date"].iloc[-1])
            if d > latest:
                latest = d
    if not latest:
        raise RuntimeError("数据 bundle 无可用 K 线")
    end_date = latest
    days = _LOOKBACK_DAYS[lookback]
    if days == 0:
        return end_date, end_date
    start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days)
    return start_dt.strftime("%Y-%m-%d"), end_date


def _wait_for_data(market: str, timeout: float = 600.0) -> None:
    """等待 data_cache 加载完成;若未在加载则触发 async 加载。"""
    if data_cache.get_market(market) is not None:
        return
    data_cache.load_market_async(market)
    deadline = time.time() + timeout
    while time.time() < deadline:
        bundle = data_cache.get_market(market)
        if bundle is not None:
            return
        status = data_cache._status_dict(market)  # noqa: SLF001 - 内部状态查询
        if status.get("error"):
            raise RuntimeError(f"数据加载失败: {status['error']}")
        time.sleep(0.5)
    raise RuntimeError("数据加载超时")


def _aggregate_scan_hits(
    events: dict[str, list[tuple[str, dict]]],
    stock_data: dict,
    market: str,
) -> list[dict]:
    """events {symbol: [(date, factors), ...]} → 每股一行的 hits 列表。"""
    hits: list[dict] = []
    for sym, evs in events.items():
        if not evs:
            continue
        # 取最近一次命中作为信号点
        last_date, last_factors = evs[-1]
        df = stock_data.get(sym)
        if df is None or df.empty:
            continue
        # 当前价 = qfq 最新 close
        current_price = float(df["close"].iloc[-1])
        # 信号日 close:精确匹配 last_date(若 missing,跳过)
        match = df.loc[df["date"] == last_date]
        if match.empty:
            signal_close = None
            change_pct = None
        else:
            signal_close = float(match["close"].iloc[0])
            change_pct = (
                (current_price - signal_close) / signal_close if signal_close else None
            )
        hits.append(
            {
                "symbol": sym,
                "name": get_stock_name(sym, market),
                "current_price": current_price,
                "signal_close": signal_close,
                "change_pct_since_signal": change_pct,
                "last_match_date": last_date,
                "match_count": len(evs),
                "factors": last_factors,
            }
        )
    # 按命中次数倒序、再按最近命中日倒序
    hits.sort(key=lambda h: (h["match_count"], h["last_match_date"]), reverse=True)
    return hits


@router.post("/scan-radar")
def api_scan_radar(body: dict = Body(...)):
    """策略雷达全市场扫描 — 选股回测,在 lookback 窗口内每根 bar 评估 screen()。

    Body:
      {strategy_class, filepath, params?, lookback, market?}
      lookback ∈ {yesterday, 1m, 1y, 3y, 5y}
    """
    class_name = body.get("strategy_class")
    filepath_str = body.get("filepath")
    lookback = body.get("lookback", "1y")
    market = (body.get("market") or "A").upper()
    data_market = resolve_data_market(market)
    overrides = body.get("params") or {}

    if not class_name or not filepath_str:
        raise HTTPException(status_code=400, detail="strategy_class 与 filepath 必填")
    if lookback not in _LOOKBACK_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"lookback 非法: {lookback},可选 {list(_LOOKBACK_DAYS.keys())}",
        )

    classes = load_strategy_from_file(Path(filepath_str))
    cls = next((c for c in classes if c.__name__ == class_name), None)
    if cls is None:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy class {class_name} not found in {filepath_str}",
        )

    intrinsic_frequency = getattr(cls, "frequency", "daily") or "daily"
    # 频率冲突兜底:非日频策略 + yesterday 单日窗口无意义
    if lookback == "yesterday" and intrinsic_frequency != "daily":
        raise HTTPException(
            status_code=400,
            detail=f"策略频率为 {intrinsic_frequency},「最新交易日」仅适用于日频策略",
        )

    strategy: Strategy = cls(param_overrides=overrides)
    intrinsic_name = getattr(cls, "name", None) or class_name
    defaults = {k: v["default"] for k, v in getattr(cls, "params", {}).items()}
    merged_params = {**defaults, **overrides}

    task_id = task_manager.create_task(
        task_type="scan-radar",
        strategy_class=class_name,
        strategy_name=intrinsic_name,
        params=merged_params,
        frequency=intrinsic_frequency,
        market=market,
    )

    def on_progress(current, total, phase=""):
        task_manager.update_progress(task_id, current, total, phase)

    def run_task():
        try:
            on_progress(0, 0, "等待数据加载...")
            _wait_for_data(data_market)
            bundle = data_cache.get_market(data_market)
            start_date, end_date = _resolve_scan_dates(bundle, lookback)
            on_progress(0, 0, f"切片数据 {start_date}~{end_date}...")
            # HK_CONNECT:把扫描全集收敛到港股通成分股
            scan_symbols = apply_market_filter(market, None)
            sliced = data_cache.slice_bundle(bundle, scan_symbols, start_date, end_date)
            if not sliced.stock_data:
                raise RuntimeError("切片后无 K 线数据")

            engine = BacktestEngine(
                strategy=strategy,
                stock_data=sliced.stock_data,
                valuation_data=sliced.valuation_data,
                dividend_data=sliced.dividend_data,
                financial_data=sliced.financial_data,
                balance_data=sliced.balance_data,
                cashflow_data=sliced.cashflow_data,
                income_data=sliced.income_data,
                weekly_data=sliced.weekly_data,
                monthly_data=sliced.monthly_data,
                iter_start=sliced.iter_start_idx,
                iter_end=sliced.iter_end_idx,
                on_progress=lambda cur, total: on_progress(cur, total, "扫描中..."),
                log_dir=LOG_DIR / "scan_radar" / task_id,
            )
            scan_result = engine.run_scan()
            hits = _aggregate_scan_hits(
                scan_result["events"], sliced.stock_data, market
            )

            # 数据最新日:bundle 内任一 df 的最大 date
            data_latest_date = ""
            for df in bundle.stock_data.values():
                if df is not None and not df.empty:
                    d = str(df["date"].iloc[-1])
                    if d > data_latest_date:
                        data_latest_date = d

            result = {
                "hits": hits,
                "total_scanned": scan_result["all_symbols_count"],
                "lookback_used": lookback,
                "date_range": {"start": start_date, "end": end_date},
                "data_latest_date": data_latest_date,
                "strategy_class": class_name,
                "strategy_name": intrinsic_name,
                "frequency": intrinsic_frequency,
            }
            task_manager.complete_task(task_id, safe_json(result))
        except Exception as e:
            task_manager.fail_task(task_id, str(e))

    threading.Thread(target=run_task, daemon=True).start()
    return {"task_id": task_id, "status": "running"}


@router.get("/scan-radar/result/{task_id}")
def api_scan_radar_result(task_id: str):
    """雷达扫描结果(独立路由,行为同 /result/{task_id} 但语义专属)。"""
    result = task_manager.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result
