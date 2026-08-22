"""统一的回测执行 seam。

该模块只负责装配现有 loader、缓存快照、引擎和任务持久化，不改变
``BacktestEngine.run`` / ``run_scan`` 的结果 schema。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

from config import LOG_DIR
from services.api_utils import safe_json
from services.backtest import data_cache
from services.backtest.data_snapshot import create_snapshot
from services.backtest.engine import BacktestEngine
from services.backtest.market_filter import resolve_data_market
from services.backtest.strategy_loader import load_strategy_from_file
from services.backtest.task_manager import TaskManager, task_manager
from services.market_data.stock_index import get_name as get_stock_name


class ExecutionMode(str, Enum):
    FULL = "full"
    SCAN = "scan"


@dataclass
class ExecutionSpec:
    mode: ExecutionMode | str
    filepath: Path | str
    strategy_class: str
    strategy_name: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    frequency: str | None = None
    market: str = "A"
    symbols: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    lookback_used: str | None = None
    task_type: str | None = None
    trigger_source: str | None = None
    log_dir: Path | str | None = None

    def __post_init__(self) -> None:
        self.mode = ExecutionMode(self.mode)
        self.filepath = Path(self.filepath)
        self.params = dict(self.params or {})
        self.market = self.market.upper()
        if self.log_dir is not None:
            self.log_dir = Path(self.log_dir)


def aggregate_scan_hits(
    events: dict[str, list[tuple[str, dict]]],
    stock_data: dict,
    market: str,
) -> list[dict]:
    """Aggregate raw scan events into the public per-symbol hit payload."""
    hits: list[dict] = []
    for sym, evs in events.items():
        if not evs:
            continue
        last_date, last_factors = evs[-1]
        df = stock_data.get(sym)
        if df is None or df.empty:
            continue
        current_price = float(df["close"].iloc[-1])
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
    hits.sort(key=lambda hit: (hit["match_count"], hit["last_match_date"]), reverse=True)
    return hits


def execute_backtest(spec: ExecutionSpec, *, task_id: str | None = None,
                     task_manager: TaskManager | None = None) -> dict:
    """同步执行一次 full 或 scan，返回引擎原始结果载荷。"""
    manager = task_manager or globals()["task_manager"]
    classes = load_strategy_from_file(Path(spec.filepath))
    strategy_cls = next(
        (candidate for candidate in classes if candidate.__name__ == spec.strategy_class),
        None,
    )
    if strategy_cls is None:
        raise ValueError(
            f"Strategy class {spec.strategy_class} not found in {spec.filepath}"
        )

    strategy = strategy_cls(param_overrides=spec.params)
    data_market = resolve_data_market(spec.market)
    bundle = data_cache.get_market(data_market)
    if bundle is None:
        page = "策略雷达" if spec.mode is ExecutionMode.SCAN else "策略回测"
        raise RuntimeError(
            f"{data_market} 市场数据未加载,请先在「{page}」页点击「加载数据」"
        )
    status = data_cache.get_status(data_market)
    snapshot = create_snapshot(
        bundle,
        data_market,
        spec.symbols,
        spec.start_date,
        spec.end_date,
        generation=status.get("generation"),
        refresh_id=status.get("refresh_id"),
        market_version=status.get("market_version"),
        stale=status.get("stale", False),
    )

    def on_progress(current: int, total: int, phase: str | None = None) -> None:
        if task_id is not None:
            progress_phase = phase or (
                "扫描中..." if spec.mode is ExecutionMode.SCAN else "回测中..."
            )
            manager.update_progress(task_id, current, total, progress_phase)

    task_log_dir = (
        Path(spec.log_dir or LOG_DIR / "backtest") / task_id
        if task_id
        else None
    )
    if task_id is not None:
        manager.update_progress(task_id, 0, 0, "切片数据中...")
    engine = BacktestEngine(
        strategy=strategy,
        snapshot=snapshot,
        on_progress=on_progress,
        log_dir=task_log_dir,
    )
    if spec.mode is ExecutionMode.SCAN:
        scan_result = engine.run_scan()
        data_latest_date = ""
        for frame in bundle.stock_data.values():
            if frame is not None and not frame.empty:
                latest = str(frame["date"].iloc[-1])
                data_latest_date = max(data_latest_date, latest)
        return {
            "hits": aggregate_scan_hits(
                scan_result["events"], snapshot.sliced.stock_data, spec.market
            ),
            "total_scanned": scan_result["all_symbols_count"],
            "lookback_used": spec.lookback_used or "custom",
            "date_range": {"start": spec.start_date, "end": spec.end_date},
            "data_latest_date": data_latest_date,
            "strategy_class": spec.strategy_class,
            "strategy_name": spec.strategy_name or getattr(strategy_cls, "name", None) or spec.strategy_class,
            "frequency": spec.frequency or getattr(strategy, "frequency", None),
            "data_context": snapshot.data_context(),
            "data_provenance": {
                "refresh_id": snapshot.refresh_id,
                "generation": snapshot.generation,
                "market_version": snapshot.market_version,
            },
        }
    return engine.run()


def submit_backtest(spec: ExecutionSpec, *, task_manager: TaskManager | None = None) -> str:
    """创建可审计任务后，在后台执行并持久化成功或失败结果。"""
    manager = task_manager or globals()["task_manager"]
    task_id = manager.create_task(
        task_type=spec.task_type or ("scan-radar" if spec.mode is ExecutionMode.SCAN else "backtest"),
        strategy_class=spec.strategy_class,
        strategy_name=spec.strategy_name,
        params=spec.params,
        frequency=spec.frequency,
        symbols=spec.symbols,
        market=spec.market,
        start_date=spec.start_date,
        end_date=spec.end_date,
        log_dir=str(spec.log_dir or LOG_DIR / "backtest"),
        trigger_source=spec.trigger_source,
    )

    def run_task() -> None:
        try:
            result = cast(
                dict,
                safe_json(
                    execute_backtest(spec, task_id=task_id, task_manager=manager)
                ),
            )
            manager.complete_task(task_id, result)
        except Exception as exc:
            manager.fail_task(task_id, str(exc))

    threading.Thread(target=run_task, daemon=True).start()
    return task_id
