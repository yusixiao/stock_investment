import math
import threading
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body

from config import QFQ_KLINE_DIR, STRATEGY_DIR
from services.backtest.strategy_loader import scan_strategies, load_strategy_from_file
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy, TraderStrategy
from services.backtest.task_manager import task_manager


router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _safe_json(obj):
    def _clean(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    def _clean_obj(o):
        if isinstance(o, dict):
            return {k: _clean_obj(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_clean_obj(i) for i in o]
        return _clean(o)

    return _clean_obj(obj)


def _extract_symbols(screened_symbols: list) -> list[str]:
    if not screened_symbols:
        return []
    if isinstance(screened_symbols[0], str):
        return list(screened_symbols)
    return [item["symbol"] for item in screened_symbols]


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
    source_task_id = body.get("source_task_id")

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

    symbols = None
    if source_task_id:
        src_result = task_manager.get_result(source_task_id)
        if src_result is None:
            raise HTTPException(status_code=400, detail=f"源任务 {source_task_id} 不存在")
        if src_result["status"] != "success":
            raise HTTPException(status_code=400, detail=f"源任务 {source_task_id} 未成功完成")
        result_data = src_result.get("result") or {}
        screened = result_data.get("screened_symbols")
        if screened is None:
            raise HTTPException(status_code=400, detail=f"源任务 {source_task_id} 不是选股任务，无选股结果")
        syms = _extract_symbols(screened)
        if not syms:
            raise HTTPException(status_code=400, detail=f"源任务 {source_task_id} 未选出任何股票")
        symbols = syms
        start_date = src_result.get("start_date") or start_date
        end_date = src_result.get("end_date") or end_date

    screeners = []
    trader = None
    for item in pipeline:
        filepath = Path(item["filepath"])
        class_name = item["class_name"]
        overrides = param_overrides.get(class_name, {})
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == class_name), None)
        if cls is None:
            raise HTTPException(status_code=400, detail=f"Strategy class {class_name} not found in {filepath}")
        instance = cls(param_overrides=overrides)
        if isinstance(instance, TraderStrategy):
            trader = instance
        elif isinstance(instance, ScreenerStrategy):
            screeners.append(instance)

    task_type = "backtest" if trader else "screener"
    pipeline_info = []
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
        pipeline_info.append(info)
    task_id = task_manager.create_task(task_type=task_type, pipeline_info=pipeline_info, start_date=start_date, end_date=end_date, source_task_id=source_task_id)

    def on_progress(current, total, phase):
        task_manager.update_progress(task_id, current, total, phase)

    def run_task():
        try:
            task_manager.update_progress(task_id, 0, 0, "加载数据中...")
            stock_data = _load_stock_data(start_date, end_date, symbols)
            task_manager.update_progress(task_id, len(stock_data), len(stock_data), f"数据加载完成 ({len(stock_data)} 只)")
            engine = BacktestEngine(stock_data=stock_data, screeners=screeners, trader=trader, on_progress=on_progress)
            result = engine.run()
            result = _safe_json(result)
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


def _load_stock_data(start_date: str = None, end_date: str = None, symbols: list[str] = None) -> dict[str, pd.DataFrame]:
    stock_data = {}
    if symbols is not None:
        filepaths = [QFQ_KLINE_DIR / f"{s}.parquet" for s in symbols]
        filepaths = [f for f in filepaths if f.exists()]
    else:
        filepaths = list(QFQ_KLINE_DIR.glob("*.parquet"))
    for filepath in filepaths:
        symbol = filepath.stem
        df = pd.read_parquet(filepath)
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        if not df.empty:
            stock_data[symbol] = df
    return stock_data
