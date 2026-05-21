"""回测 API(Phase 6.2 适配单一 Strategy 模型)。

旧多策略 pipeline + TraderStrategy/ScreenerStrategy 区分已废弃。现仅接受单一
Strategy class — 前端仍以 pipeline=[item] 形式提交,后端取首项实例化为 Strategy。
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Body, HTTPException

from config import (
    DIVIDEND_DIR,
    FINANCIAL_DIR,
    LOG_DIR,
    STRATEGY_DIR,
    VALUATION_DIR,
)
from services.api_utils import safe_json
from services.backtest.engine import BacktestEngine
from services.backtest.strategy_loader import load_strategy_from_file, scan_strategies
from services.backtest.task_manager import task_manager
from services.duckdb_store import get_store
from strategies.base import Strategy


router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/strategies")
def api_list_strategies():
    if not STRATEGY_DIR.exists():
        return []
    return scan_strategies(STRATEGY_DIR)


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
    market = body.get("market", "A")

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
            task_manager.update_progress(task_id, 0, 0, "加载数据中...")
            stock_data = _load_stock_data(
                start_date, end_date, target_symbols, market=market
            )
            # 三个 parquet 目录的加载彼此完全独立(读不同目录、不同 symbol 子集均可),
            # 串行 ~14s,并行后取最慢一路 ~5s,省 ~9s/回测。
            # GIL 不影响 — 主要耗时在 pyarrow C 层 read_parquet 和文件 IO,均会释放 GIL。
            symbols = list(stock_data.keys())
            with ThreadPoolExecutor(max_workers=3) as pool:
                fut_val = pool.submit(_load_valuation_data, symbols)
                fut_div = pool.submit(_load_dividend_data, symbols)
                fut_fin = pool.submit(_load_financial_data, symbols)
                valuation_data = fut_val.result()
                dividend_data = fut_div.result()
                financial_data = fut_fin.result()
            task_manager.update_progress(
                task_id,
                len(stock_data),
                len(stock_data),
                f"数据加载完成 ({len(stock_data)} 只)",
            )
            # 决策日志目录:每个 task 独立子目录,与 task_manager 内部默认路径一致
            task_log_dir = LOG_DIR / "backtest" / task_id
            engine = BacktestEngine(
                strategy=strategy,
                stock_data=stock_data,
                valuation_data=valuation_data,
                dividend_data=dividend_data,
                financial_data=financial_data,
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

    使用 query_qfq_kline_bulk 一次 SQL 取所有股票数据 + groupby 拆 dict,
    全市场加载可比 N+1 循环快 ~240x。

    - symbols 为空/None → 全市场模式
    - start_date/end_date 为 None → 不限制日期范围
    """
    store = get_store()
    return store.query_qfq_kline_bulk(
        market=market,
        symbols=symbols if symbols else None,
        start=start_date,
        end=end_date,
    )
