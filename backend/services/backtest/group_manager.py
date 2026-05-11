import json
import sqlite3
import uuid
from datetime import datetime

from config import PORTFOLIO_DB


class GroupManager:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or str(PORTFOLIO_DB)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_tables(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_groups (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    pipeline TEXT NOT NULL,
                    join_modes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            try:
                conn.execute("ALTER TABLE strategy_groups ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_exclusions (
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, symbol)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_runs (
                    run_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    execution_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step INTEGER DEFAULT 0,
                    steps_result TEXT,
                    final_result TEXT,
                    summary TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES strategy_groups(group_id)
                )
            """)
            try:
                conn.execute("ALTER TABLE group_runs ADD COLUMN initial_capital REAL NOT NULL DEFAULT 1000000")
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()

    def create_group(self, name: str, pipeline: list[dict], join_modes: list[str] | None = None) -> str:
        group_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO strategy_groups (group_id, name, pipeline, join_modes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (group_id, name, json.dumps(pipeline, ensure_ascii=False), json.dumps(join_modes or [], ensure_ascii=False), now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return group_id

    def get_group(self, group_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM strategy_groups WHERE group_id = ?", (group_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "group_id": row["group_id"],
            "name": row["name"],
            "pipeline": json.loads(row["pipeline"]),
            "join_modes": json.loads(row["join_modes"]) if row["join_modes"] else [],
            "archived": bool(row["archived"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_groups(self) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM strategy_groups ORDER BY archived ASC, updated_at DESC").fetchall()
            result = []
            for row in rows:
                group = {
                    "group_id": row["group_id"],
                    "name": row["name"],
                    "pipeline": json.loads(row["pipeline"]),
                    "join_modes": json.loads(row["join_modes"]) if row["join_modes"] else [],
                    "archived": bool(row["archived"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                run_row = conn.execute(
                    "SELECT count(*) as cnt, max(created_at) as last_run FROM group_runs WHERE group_id = ?",
                    (row["group_id"],),
                ).fetchone()
                group["run_count"] = run_row["cnt"]
                group["last_run"] = run_row["last_run"]
                result.append(group)
        finally:
            conn.close()
        return result

    def update_group(self, group_id: str, name: str | None = None, pipeline: list[dict] | None = None, join_modes: list[str] | None = None):
        conn = self._get_conn()
        try:
            updates = []
            params = []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if pipeline is not None:
                updates.append("pipeline = ?")
                params.append(json.dumps(pipeline, ensure_ascii=False))
            if join_modes is not None:
                updates.append("join_modes = ?")
                params.append(json.dumps(join_modes, ensure_ascii=False))
            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(group_id)
                conn.execute(f"UPDATE strategy_groups SET {', '.join(updates)} WHERE group_id = ?", params)
                conn.commit()
        finally:
            conn.close()

    def delete_group(self, group_id: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM group_runs WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM strategy_groups WHERE group_id = ?", (group_id,))
            conn.commit()
        finally:
            conn.close()

    def archive_group(self, group_id: str, archived: bool = True):
        conn = self._get_conn()
        try:
            conn.execute("UPDATE strategy_groups SET archived = ? WHERE group_id = ?", (1 if archived else 0, group_id))
            conn.commit()
        finally:
            conn.close()

    def create_run(self, group_id: str, start_date: str | None, end_date: str | None, execution_mode: str, initial_capital: float = 1_000_000) -> str:
        run_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO group_runs (run_id, group_id, start_date, end_date, execution_mode, status, current_step, steps_result, initial_capital, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, group_id, start_date, end_date, execution_mode, "running", 0, "[]", initial_capital, now),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM group_runs WHERE run_id = ?", (run_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "group_id": row["group_id"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "execution_mode": row["execution_mode"],
            "status": row["status"],
            "current_step": row["current_step"],
            "steps_result": json.loads(row["steps_result"]) if row["steps_result"] else [],
            "final_result": json.loads(row["final_result"]) if row["final_result"] else None,
            "summary": json.loads(row["summary"]) if row["summary"] else None,
            "initial_capital": row["initial_capital"],
            "error": row["error"],
            "created_at": row["created_at"],
        }

    def list_runs(self, group_id: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM group_runs WHERE group_id = ? ORDER BY created_at DESC", (group_id,)).fetchall()
        finally:
            conn.close()
        result = []
        for row in rows:
            result.append({
                "run_id": row["run_id"],
                "group_id": row["group_id"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "execution_mode": row["execution_mode"],
                "status": row["status"],
                "current_step": row["current_step"],
                "summary": json.loads(row["summary"]) if row["summary"] else None,
                "error": row["error"],
                "created_at": row["created_at"],
            })
        return result

    def update_run_step(self, run_id: str, step: int, steps_result: list[dict]):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE group_runs SET current_step = ?, steps_result = ? WHERE run_id = ?",
                (step, json.dumps(steps_result, ensure_ascii=False), run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_run_status(self, run_id: str, status: str, final_result: dict | None = None, summary: dict | None = None, error: str | None = None):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE group_runs SET status = ?, final_result = ?, summary = ?, error = ? WHERE run_id = ?",
                (status, json.dumps(final_result, ensure_ascii=False) if final_result else None, json.dumps(summary, ensure_ascii=False) if summary else None, error, run_id),
            )
            conn.commit()
        finally:
            conn.close()


    def add_exclusion(self, run_id: str, symbol: str, reason: str = ""):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO stock_exclusions (run_id, symbol, reason, created_at) VALUES (?, ?, ?, ?)",
                (run_id, symbol, reason, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def remove_exclusion(self, run_id: str, symbol: str):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM stock_exclusions WHERE run_id = ? AND symbol = ?", (run_id, symbol))
            conn.commit()
        finally:
            conn.close()

    def list_exclusions(self, run_id: str) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT symbol, reason, created_at FROM stock_exclusions WHERE run_id = ?", (run_id,)).fetchall()
        finally:
            conn.close()
        return [{"symbol": row["symbol"], "reason": row["reason"], "created_at": row["created_at"]} for row in rows]

    def get_effective_symbols(self, run_id: str) -> list[str]:
        run = self.get_run(run_id)
        if not run or not run["steps_result"]:
            return []
        all_symbols = run["steps_result"][-1].get("symbols", [])
        exclusions = {e["symbol"] for e in self.list_exclusions(run_id)}
        return [s for s in all_symbols if s not in exclusions]

    def migrate_from_tasks(self, task_manager) -> int:
        tasks = task_manager.list_tasks(show_deleted=False)
        source_map = {}
        task_map = {}
        for t in tasks:
            task_map[t["task_id"]] = t
            if t.get("source_task_id"):
                source_map[t["task_id"]] = t["source_task_id"]

        children = {}
        for child_id, parent_id in source_map.items():
            children.setdefault(parent_id, []).append(child_id)

        roots = set()
        for child_id in source_map:
            parent_id = source_map[child_id]
            if parent_id not in source_map:
                roots.add(parent_id)

        count = 0
        for root_id in roots:
            chain = [root_id]
            current = root_id
            while current in children:
                next_ids = children[current]
                current = next_ids[0]
                chain.append(current)

            pipeline = []
            for tid in chain:
                result = task_manager.get_result(tid)
                if result and result.get("pipeline_info"):
                    pi = result["pipeline_info"]
                    if isinstance(pi, list):
                        strategies = pi
                    else:
                        strategies = pi.get("strategies", [pi] if "class_name" in pi else [])
                    for s in strategies:
                        item = {
                            "filepath": s.get("filepath", ""),
                            "class_name": s.get("class_name", ""),
                            "frequency": s.get("frequency", "daily"),
                            "params": s.get("params", {}),
                        }
                        if s.get("name"):
                            item["name"] = s["name"]
                        pipeline.append(item)

            if len(pipeline) < 2:
                continue

            from datetime import datetime as _dt
            name = f"迁移-{_dt.now().strftime('%Y%m%d')}-#{count + 1}"
            first_task = task_manager.get_result(chain[0])
            start_date = first_task.get("start_date", "")
            end_date = first_task.get("end_date", "")

            join_modes = ["correlated"] * (len(pipeline) - 1)
            group_id = self.create_group(name, pipeline, join_modes)

            run_id = self.create_run(group_id, start_date, end_date, "auto")
            steps_result = []
            last_result = None
            for i, tid in enumerate(chain):
                r = task_manager.get_result(tid)
                result_data = r.get("result") or {}
                syms = _extract_symbols_from_result(result_data) if result_data else []
                steps_result.append({
                    "step": i + 1,
                    "input_count": 0 if i == 0 else steps_result[i - 1]["output_count"],
                    "output_count": len(syms),
                    "symbols": syms,
                    "task_id": tid,
                })
                last_result = result_data

            self.update_run_step(run_id, len(chain), steps_result)
            summary = None
            if last_result:
                if "screened_symbols" in last_result:
                    summary = {"screened_count": len(last_result["screened_symbols"])}
                elif "metrics" in last_result:
                    m = last_result["metrics"]
                    summary = {"total_return": m.get("total_return"), "max_drawdown": m.get("max_drawdown")}
            self.update_run_status(run_id, "success", final_result=last_result, summary=summary)
            count += 1

        return count


group_manager_instance = GroupManager()

import threading
from pathlib import Path
from services.backtest.task_manager import TaskManager, task_manager as default_task_manager
from services.backtest.strategy_loader import load_strategy_from_file
from services.backtest.base import ScreenerStrategy, TraderStrategy, BuyStrategy, SellStrategy
from services.qfq_cache import get_qfq_kline
from config import RAW_KLINE_DIR, VALUATION_DIR, DIVIDEND_DIR, FINANCIAL_DIR


def _extract_symbols_from_result(result: dict) -> list[str]:
    screened = result.get("screened_symbols", [])
    if not screened:
        return []
    if isinstance(screened[0], str):
        return list(screened)
    return [item["symbol"] for item in screened]


def _execute_step(step_config: dict, start_date: str, end_date: str, symbols: list[str] | None, task_manager: TaskManager) -> tuple[str, dict]:
    from services.backtest.engine import BacktestEngine
    from services.qfq_cache import get_qfq_kline
    from config import RAW_KLINE_DIR, VALUATION_DIR, DIVIDEND_DIR, FINANCIAL_DIR
    import pandas as pd

    filepath = Path(step_config["filepath"])
    class_name = step_config["class_name"]
    params = step_config.get("params", {})

    classes = load_strategy_from_file(filepath)
    cls = next((c for c in classes if c.__name__ == class_name), None)
    if cls is None:
        raise ValueError(f"Strategy class {class_name} not found in {filepath}")
    instance = cls(param_overrides=params)

    screeners = []
    trader = None
    if isinstance(instance, TraderStrategy):
        trader = instance
    else:
        screeners = [instance]

    task_type = "backtest" if trader else "screener"
    task_id = task_manager.create_task(task_type=task_type, start_date=start_date, end_date=end_date)

    if symbols is not None:
        target_symbols = symbols
    else:
        target_symbols = [f.stem for f in RAW_KLINE_DIR.glob("*.parquet")]

    stock_data = {}
    for sym in target_symbols:
        df = get_qfq_kline(sym, start_date=start_date, end_date=end_date)
        if not df.empty:
            stock_data[sym] = df

    valuation_data = {}
    for sym in stock_data:
        fp = VALUATION_DIR / f"{sym}.parquet"
        if fp.exists():
            valuation_data[sym] = pd.read_parquet(fp).sort_values("date").reset_index(drop=True)

    dividend_data = {}
    for sym in stock_data:
        fp = DIVIDEND_DIR / f"{sym}.parquet"
        if fp.exists():
            dividend_data[sym] = pd.read_parquet(fp)

    financial_data = {}
    for sym in stock_data:
        fp = FINANCIAL_DIR / f"{sym}.parquet"
        if fp.exists():
            financial_data[sym] = pd.read_parquet(fp).sort_values("报告期").reset_index(drop=True)

    engine = BacktestEngine(
        stock_data=stock_data,
        screeners=screeners,
        trader=trader,
        valuation_data=valuation_data,
        dividend_data=dividend_data,
        financial_data=financial_data,
    )
    result = engine.run()
    task_manager.complete_task(task_id, result)
    return task_id, result


def _execute_buy_sell_steps(
    screener_configs: list[dict],
    buyer_config: dict | None,
    seller_config: dict | None,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    initial_capital: float,
    task_manager: TaskManager,
    signal_table: dict[str, list[str]] | None = None,
    join_modes: list[str] | None = None,
) -> tuple[str, dict]:
    from services.backtest.buy_sell_engine import BuySellEngine
    import pandas as pd

    screeners = []
    for cfg in screener_configs:
        filepath = Path(cfg["filepath"])
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == cfg["class_name"]), None)
        if cls is None:
            raise ValueError(f"Strategy class {cfg['class_name']} not found in {filepath}")
        screeners.append(cls(param_overrides=cfg.get("params", {})))

    buyer = None
    if buyer_config:
        filepath = Path(buyer_config["filepath"])
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == buyer_config["class_name"]), None)
        if cls is None:
            raise ValueError(f"Strategy class {buyer_config['class_name']} not found in {filepath}")
        buyer = cls(param_overrides=buyer_config.get("params", {}))

    seller = None
    if seller_config:
        filepath = Path(seller_config["filepath"])
        classes = load_strategy_from_file(filepath)
        cls = next((c for c in classes if c.__name__ == seller_config["class_name"]), None)
        if cls is None:
            raise ValueError(f"Strategy class {seller_config['class_name']} not found in {filepath}")
        seller = cls(param_overrides=seller_config.get("params", {}))

    if symbols is not None:
        target_symbols = symbols
    else:
        target_symbols = [f.stem for f in RAW_KLINE_DIR.glob("*.parquet")]

    stock_data = {}
    for sym in target_symbols:
        df = get_qfq_kline(sym, start_date=start_date, end_date=end_date)
        if not df.empty:
            stock_data[sym] = df

    valuation_data = {}
    for sym in stock_data:
        fp = VALUATION_DIR / f"{sym}.parquet"
        if fp.exists():
            valuation_data[sym] = pd.read_parquet(fp).sort_values("date").reset_index(drop=True)

    dividend_data = {}
    for sym in stock_data:
        fp = DIVIDEND_DIR / f"{sym}.parquet"
        if fp.exists():
            dividend_data[sym] = pd.read_parquet(fp)

    financial_data = {}
    for sym in stock_data:
        fp = FINANCIAL_DIR / f"{sym}.parquet"
        if fp.exists():
            financial_data[sym] = pd.read_parquet(fp).sort_values("报告期").reset_index(drop=True)

    task_id = task_manager.create_task(task_type="backtest", start_date=start_date, end_date=end_date)

    engine = BuySellEngine(
        stock_data=stock_data,
        screeners=screeners,
        buyer=buyer,
        seller=seller,
        initial_capital=initial_capital,
        signal_table=signal_table,
        valuation_data=valuation_data,
        dividend_data=dividend_data,
        financial_data=financial_data,
        join_modes=join_modes,
    )
    result = engine.run()
    task_manager.complete_task(task_id, result)
    return task_id, result


class GroupRunner:
    def __init__(self, group_manager: GroupManager | None = None, task_manager: TaskManager | None = None):
        self._group_manager = group_manager or group_manager_instance
        self._task_manager = task_manager or default_task_manager

    def run_auto(self, group_id: str, start_date: str, end_date: str, source_run_id: str = None, initial_capital: float = 1_000_000) -> str:
        gm = self._group_manager
        group = gm.get_group(group_id)
        if group is None:
            raise ValueError(f"Group {group_id} not found")

        run_id = gm.create_run(group_id, start_date, end_date, "auto", initial_capital=initial_capital)
        self._run_auto_with_run_id(run_id, group_id, start_date, end_date, source_run_id, initial_capital=initial_capital)
        return run_id

    def run_stepwise_start(self, group_id: str, start_date: str, end_date: str) -> str:
        gm = self._group_manager
        group = gm.get_group(group_id)
        if group is None:
            raise ValueError(f"Group {group_id} not found")

        pipeline = group["pipeline"]
        run_id = gm.create_run(group_id, start_date, end_date, "stepwise")

        step_config = pipeline[0]
        task_id, result = _execute_step(step_config, start_date, end_date, None, self._task_manager)
        output_symbols = _extract_symbols_from_result(result)

        steps_result = [{
            "step": 1,
            "input_count": 0,
            "output_count": len(output_symbols),
            "symbols": output_symbols,
            "task_id": task_id,
        }]
        gm.update_run_step(run_id, 1, steps_result)

        if len(pipeline) == 1:
            summary = self._build_summary(result)
            gm.update_run_status(run_id, "success", final_result=result, summary=summary)
        else:
            gm.update_run_status(run_id, "step_1_done")

        return run_id

    def run_stepwise_next(self, run_id: str):
        gm = self._group_manager
        run = gm.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        group = gm.get_group(run["group_id"])
        pipeline = group["pipeline"]
        join_modes = group["join_modes"]
        current_step = run["current_step"]
        next_step_idx = current_step

        if next_step_idx >= len(pipeline):
            return

        steps_result = run["steps_result"]
        prev_symbols = steps_result[-1]["symbols"] if steps_result else None

        join_mode = join_modes[next_step_idx - 1] if next_step_idx > 0 and next_step_idx - 1 < len(join_modes) else "independent"
        if join_mode == "independent":
            input_symbols = None
        else:
            input_symbols = prev_symbols

        input_count = len(input_symbols) if input_symbols else 0
        step_config = pipeline[next_step_idx]
        task_id, result = _execute_step(step_config, run["start_date"], run["end_date"], input_symbols, self._task_manager)
        output_symbols = _extract_symbols_from_result(result)

        step_info = {
            "step": next_step_idx + 1,
            "input_count": input_count,
            "output_count": len(output_symbols),
            "symbols": output_symbols,
            "task_id": task_id,
        }
        steps_result.append(step_info)
        gm.update_run_step(run_id, next_step_idx + 1, steps_result)

        if next_step_idx + 1 >= len(pipeline):
            summary = self._build_summary(result)
            gm.update_run_status(run_id, "success", final_result=result, summary=summary)
        else:
            gm.update_run_status(run_id, f"step_{next_step_idx + 1}_done")

    def _has_buy_sell(self, pipeline: list[dict]) -> bool:
        for step in pipeline:
            try:
                filepath = Path(step["filepath"])
                classes = load_strategy_from_file(filepath)
                cls = next((c for c in classes if c.__name__ == step["class_name"]), None)
                if cls and (issubclass(cls, BuyStrategy) or issubclass(cls, SellStrategy)):
                    return True
            except Exception:
                continue
        return False

    def _split_pipeline(self, pipeline: list[dict]) -> tuple[list[dict], dict | None, dict | None]:
        screener_configs = []
        buyer_config = None
        seller_config = None
        for step in pipeline:
            filepath = Path(step["filepath"])
            classes = load_strategy_from_file(filepath)
            cls = next((c for c in classes if c.__name__ == step["class_name"]), None)
            if cls is None:
                continue
            if issubclass(cls, BuyStrategy):
                buyer_config = step
            elif issubclass(cls, SellStrategy):
                seller_config = step
            elif issubclass(cls, ScreenerStrategy):
                screener_configs.append(step)
        return screener_configs, buyer_config, seller_config

    def _build_signal_table(self, final_result: dict, source_run_id: str) -> dict[str, list[str]]:
        gm = self._group_manager
        exclusions = {e["symbol"] for e in gm.list_exclusions(source_run_id)}
        screened = final_result.get("screened_symbols", [])
        table: dict[str, list[str]] = {}
        for item in screened:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol", "")
            if symbol in exclusions:
                continue
            for d in item.get("match_dates", []):
                if len(d) == 10:
                    table.setdefault(d, []).append(symbol)
        return table

    def _run_auto_with_run_id(self, run_id: str, group_id: str, start_date: str, end_date: str, source_run_id: str = None, initial_capital: float = 1_000_000):
        gm = self._group_manager
        group = gm.get_group(group_id)
        pipeline = group["pipeline"]
        join_modes = group["join_modes"]

        initial_symbols = None
        if source_run_id:
            initial_symbols = gm.get_effective_symbols(source_run_id)

        try:
            if self._has_buy_sell(pipeline):
                screener_configs, buyer_config, seller_config = self._split_pipeline(pipeline)

                signal_table = None
                symbols = initial_symbols
                if source_run_id:
                    source_run = gm.get_run(source_run_id)
                    if source_run and source_run.get("final_result"):
                        signal_table = self._build_signal_table(source_run["final_result"], source_run_id)

                screener_join_modes = join_modes[:max(0, len(screener_configs) - 1)] if join_modes else None

                task_id, result = _execute_buy_sell_steps(
                    screener_configs=screener_configs,
                    buyer_config=buyer_config,
                    seller_config=seller_config,
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                    initial_capital=initial_capital,
                    task_manager=self._task_manager,
                    signal_table=signal_table,
                    join_modes=screener_join_modes,
                )

                steps_result = [{
                    "step": 1,
                    "input_count": len(symbols) if symbols else 0,
                    "output_count": 0,
                    "symbols": [],
                    "task_id": task_id,
                }]
                gm.update_run_step(run_id, 1, steps_result)
                summary = self._build_summary(result)
                gm.update_run_status(run_id, "success", final_result=result, summary=summary)
                return

            steps_result = []
            prev_symbols = initial_symbols
            for i, step_config in enumerate(pipeline):
                join_mode = join_modes[i - 1] if i > 0 and i - 1 < len(join_modes) else "independent"
                if i == 0:
                    input_symbols = initial_symbols
                elif join_mode == "independent":
                    input_symbols = None
                else:
                    input_symbols = prev_symbols

                input_count = len(input_symbols) if input_symbols else 0
                task_id, result = _execute_step(step_config, start_date, end_date, input_symbols, self._task_manager)
                output_symbols = _extract_symbols_from_result(result)

                step_info = {
                    "step": i + 1,
                    "input_count": input_count,
                    "output_count": len(output_symbols),
                    "symbols": output_symbols,
                    "task_id": task_id,
                }
                steps_result.append(step_info)
                gm.update_run_step(run_id, i + 1, steps_result)
                prev_symbols = output_symbols

            final_result = result
            summary = self._build_summary(final_result)
            gm.update_run_status(run_id, "success", final_result=final_result, summary=summary)
        except Exception as e:
            gm.update_run_status(run_id, "failed", error=str(e))

    def _build_summary(self, result: dict) -> dict | None:
        if "screened_symbols" in result:
            items = result["screened_symbols"]
            return {"screened_count": len(items)}
        if "metrics" in result:
            m = result["metrics"]
            return {
                "total_return": m.get("total_return"),
                "max_drawdown": m.get("max_drawdown"),
            }
        return None


group_runner = GroupRunner()
