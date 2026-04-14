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

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

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
    task_id = task_manager.create_task(task_type=task_type, pipeline_info=pipeline_info)

    def on_progress(current, total, phase):
        task_manager.update_progress(task_id, current, total, phase)

    def run_task():
        try:
            task_manager.update_progress(task_id, 0, 0, "加载数据中...")
            stock_data = _load_stock_data(start_date, end_date)
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
def api_list_tasks():
    return task_manager.list_tasks()


def _load_stock_data(start_date: str = None, end_date: str = None) -> dict[str, pd.DataFrame]:
    stock_data = {}
    for filepath in QFQ_KLINE_DIR.glob("*.parquet"):
        symbol = filepath.stem
        df = pd.read_parquet(filepath)
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]
        if not df.empty:
            stock_data[symbol] = df
    return stock_data
