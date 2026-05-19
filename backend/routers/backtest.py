import threading
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body

from config import (
    STRATEGY_DIR,
    VALUATION_DIR,
    DIVIDEND_DIR,
    FINANCIAL_DIR,
)
from services.duckdb_store import get_store
from services.backtest.strategy_loader import scan_strategies, load_strategy_from_file
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.task_manager import task_manager
from services.api_utils import safe_json


router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/strategies")
def api_list_strategies():
    if not STRATEGY_DIR.exists():
        return []
    return scan_strategies(STRATEGY_DIR)


@router.post("/run")
def api_run_backtest(body: dict = Body(...)):
    pipeline = body.get("pipeline", [])
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    param_overrides = body.get("param_overrides", {})
    target_symbols = body.get("symbols")
    market = body.get("market", "A")

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

    symbols = target_symbols

    screeners = []
    trader = None
    for item in pipeline:
        filepath = Path(item["filepath"])
        class_name = item["class_name"]
        overrides = param_overrides.get(class_name, {})
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == class_name), None)
        if cls is None:
            raise HTTPException(
                status_code=400,
                detail=f"Strategy class {class_name} not found in {filepath}",
            )
        instance = cls(param_overrides=overrides)
        if isinstance(instance, TraderStrategy):
            trader = instance
        elif isinstance(instance, ScreenerStrategy):
            screeners.append(instance)

    task_type = "backtest" if trader else "screener"
    screener_infos = []
    for item in pipeline:
        cls_name = item["class_name"]
        overrides = param_overrides.get(cls_name, {})
        classes = load_strategy_from_file(Path(item["filepath"]))
        cls = next((c for c in classes if c.__name__ == cls_name), None)
        info = {"class_name": cls_name}
        if cls:
            info["name"] = getattr(cls, "name", cls_name)
            info["strategy_type"] = getattr(cls, "strategy_type", "")
            if hasattr(cls, "frequency"):
                info["frequency"] = cls.frequency
            defaults = {k: v["default"] for k, v in getattr(cls, "params", {}).items()}
            merged = {**defaults, **overrides}
            info["params"] = merged
        screener_infos.append(info)
    pipeline_info = {"strategies": screener_infos}
    task_id = task_manager.create_task(
        task_type=task_type,
        pipeline_info=pipeline_info,
        start_date=start_date,
        end_date=end_date,
    )

    def on_progress(current, total, phase):
        task_manager.update_progress(task_id, current, total, phase)

    def run_task():
        try:
            task_manager.update_progress(task_id, 0, 0, "加载数据中...")
            stock_data = _load_stock_data(start_date, end_date, symbols, market=market)
            valuation_data = _load_valuation_data(list(stock_data.keys()))
            dividend_data = _load_dividend_data(list(stock_data.keys()))
            financial_data = _load_financial_data(list(stock_data.keys()))
            task_manager.update_progress(
                task_id,
                len(stock_data),
                len(stock_data),
                f"数据加载完成 ({len(stock_data)} 只)",
            )
            engine = BacktestEngine(
                stock_data=stock_data,
                screeners=screeners,
                trader=trader,
                on_progress=on_progress,
                valuation_data=valuation_data,
                dividend_data=dividend_data,
                financial_data=financial_data,
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


def _load_financial_data(symbols: list[str]) -> dict[str, pd.DataFrame]:
    financial_data = {}
    for sym in symbols:
        filepath = FINANCIAL_DIR / f"{sym}.parquet"
        if filepath.exists():
            df = pd.read_parquet(filepath)
            df = df.sort_values("报告期").reset_index(drop=True)
            financial_data[sym] = df
    return financial_data


def _load_dividend_data(symbols: list[str]) -> dict[str, pd.DataFrame]:
    dividend_data = {}
    for sym in symbols:
        filepath = DIVIDEND_DIR / f"{sym}.parquet"
        if filepath.exists():
            df = pd.read_parquet(filepath)
            dividend_data[sym] = df
    return dividend_data


def _load_valuation_data(symbols: list[str]) -> dict[str, pd.DataFrame]:
    valuation_data = {}
    for sym in symbols:
        filepath = VALUATION_DIR / f"{sym}.parquet"
        if filepath.exists():
            df = pd.read_parquet(filepath)
            df = df.sort_values("date").reset_index(drop=True)
            valuation_data[sym] = df
    return valuation_data


def _load_stock_data(
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: list[str] | None = None,
    market: str = "A",
) -> dict[str, pd.DataFrame]:
    """通过 DuckDBStore 加载前复权 K 线，禁止 glob parquet 旧路径。

    - symbols 为空/None → 走全市场模式，用 store.list_symbols(market) 枚举
    - start_date/end_date 为 None → 不限制日期范围
    - 命中空数据的 symbol 自动跳过
    """
    store = get_store()
    if symbols:
        target_symbols = symbols
    else:
        target_symbols = store.list_symbols(market)
    stock_data: dict[str, pd.DataFrame] = {}
    for symbol in target_symbols:
        df = store.query_qfq_kline(market, symbol, start_date, end_date)
        if df is not None and not df.empty:
            stock_data[symbol] = df
    return stock_data
