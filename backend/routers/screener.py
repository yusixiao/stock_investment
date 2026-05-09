import pandas as pd
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body

from config import RAW_KLINE_DIR, STRATEGY_DIR
from services.backtest.strategy_loader import load_strategy_from_file
from services.backtest.engine import BacktestEngine
from services.backtest.base import ScreenerStrategy
from services.qfq_cache import get_qfq_kline


router = APIRouter(prefix="/api/screener", tags=["screener"])

_latest_result: dict | None = None


@router.post("/run")
def api_run_screener(body: dict = Body(...)):
    global _latest_result
    pipeline = body.get("pipeline", [])
    param_overrides = body.get("param_overrides", {})

    if not pipeline:
        raise HTTPException(status_code=400, detail="Pipeline cannot be empty")

    screeners = []
    for item in pipeline:
        filepath = Path(item["filepath"])
        class_name = item["class_name"]
        overrides = param_overrides.get(class_name, {})
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == class_name), None)
        if cls is None:
            raise HTTPException(status_code=400, detail=f"Strategy class {class_name} not found")
        instance = cls(param_overrides=overrides)
        if not isinstance(instance, ScreenerStrategy):
            raise HTTPException(status_code=400, detail=f"{class_name} is not a ScreenerStrategy")
        screeners.append(instance)

    stock_data = {}
    for filepath in RAW_KLINE_DIR.glob("*.parquet"):
        symbol = filepath.stem
        df = get_qfq_kline(symbol)
        if not df.empty:
            stock_data[symbol] = df

    engine = BacktestEngine(stock_data=stock_data, screeners=screeners, trader=None)
    result = engine.run(mode="screen")

    _latest_result = {
        "screened_symbols": result["screened_symbols"],
        "count": len(result["screened_symbols"]),
        "pipeline": [item["class_name"] for item in pipeline],
    }
    return _latest_result


@router.get("/result")
def api_get_screener_result():
    if _latest_result is None:
        return {"screened_symbols": [], "count": 0, "pipeline": []}
    return _latest_result
