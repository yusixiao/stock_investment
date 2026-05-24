"""Phase 4.7 (D6): backtest_tasks schema migration tests.

覆盖:
1. 空旧库迁移成功 (新库直接建表 + ALTER 路径幂等)
2. 含 1 个旧任务迁移后 pipeline_info 形态正确 (旧 {pipeline:[...]} -> 新 {strategy_class, params})
3. 软删后 list_tasks 默认不返回
4. include_deleted=True 返回全部 (含已删)
"""

import json
import sqlite3
from datetime import datetime

import pytest

from services.backtest.task_manager import TaskManager
from services.db_schema import init_backtest_tables, run_merge_strategies_migration


def _create_legacy_schema(conn: sqlite3.Connection):
    """模拟 T4.7 之前的老库 schema (无 is_deleted / log_dir)。"""
    conn.executescript(
        """
        CREATE TABLE backtest_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            task_type TEXT NOT NULL DEFAULT 'screener',
            pipeline_info TEXT,
            start_date TEXT,
            end_date TEXT,
            summary TEXT,
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            source_task_id TEXT,
            deleted INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_migration_on_empty_legacy_db(tmp_path):
    """场景 1: 空旧库迁移幂等成功, 列被加入。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    _create_legacy_schema(conn)
    assert "is_deleted" not in _columns(conn, "backtest_tasks")

    run_merge_strategies_migration(conn)
    cols = _columns(conn, "backtest_tasks")
    assert "is_deleted" in cols
    assert "log_dir" in cols

    # 二次执行仍然 OK (幂等)
    run_merge_strategies_migration(conn)
    conn.close()


def test_migration_rewrites_old_pipeline_info(tmp_path):
    """场景 2: 旧 pipeline_info {pipeline: [{class_name, params}]} -> {strategy_class, params}。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    _create_legacy_schema(conn)
    old_pi = {"pipeline": [{"class_name": "RoeScreener", "params": {"min_roe": 15}}]}
    conn.execute(
        "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            "old001",
            "success",
            "screener",
            json.dumps(old_pi),
            datetime.now().isoformat(),
        ),
    )
    # 新格式 {strategies:[...]} 应保持不动
    new_pi = {"strategies": [{"name": "X"}], "join_modes": []}
    conn.execute(
        "INSERT INTO backtest_tasks (task_id, status, task_type, pipeline_info, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            "new001",
            "success",
            "screener",
            json.dumps(new_pi),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()

    run_merge_strategies_migration(conn)

    row = conn.execute(
        "SELECT pipeline_info FROM backtest_tasks WHERE task_id = ?", ("old001",)
    ).fetchone()
    migrated = json.loads(row[0])
    assert migrated == {"strategy_class": "RoeScreener", "params": {"min_roe": 15}}

    row2 = conn.execute(
        "SELECT pipeline_info FROM backtest_tasks WHERE task_id = ?", ("new001",)
    ).fetchone()
    assert json.loads(row2[0]) == new_pi
    conn.close()


def test_soft_delete_filters_by_default(tmp_path):
    """场景 3: 软删后 list_tasks 默认不返回该任务。"""
    db = tmp_path / "tm.db"
    tm = TaskManager(db_path=str(db))
    tid = tm.create_task(strategy_class="X", params={"a": 1})
    assert any(t["task_id"] == tid for t in tm.list_tasks())

    tm.delete_task(tid)
    assert all(t["task_id"] != tid for t in tm.list_tasks())


def test_include_deleted_returns_soft_deleted(tmp_path):
    """场景 4: include_deleted=True 返回所有任务 (含已删)。"""
    db = tmp_path / "tm.db"
    tm = TaskManager(db_path=str(db))
    tid = tm.create_task(strategy_class="X", params={})
    tm.delete_task(tid)

    all_tasks = tm.list_tasks(include_deleted=True)
    target = next((t for t in all_tasks if t["task_id"] == tid), None)
    assert target is not None
    assert target["deleted"] is True


def test_create_task_writes_strategy_class_and_log_dir(tmp_path):
    """新 schema 写入: pipeline_info = {strategy_class, params}, log_dir 派生。"""
    db = tmp_path / "tm.db"
    tm = TaskManager(db_path=str(db))
    tid = tm.create_task(strategy_class="RoeScreener", params={"min_roe": 12})

    res = tm.get_result(tid)
    assert res["pipeline_info"] == {
        "strategy_class": "RoeScreener",
        "params": {"min_roe": 12},
    }
    assert res["log_dir"] == f"logs/backtest/{tid}/"


def test_init_backtest_tables_on_fresh_db_includes_new_columns(tmp_path):
    """新建库直接含 is_deleted / log_dir 列, 不依赖 migration runner。"""
    db = tmp_path / "fresh.db"
    conn = sqlite3.connect(db)
    init_backtest_tables(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(backtest_tasks)").fetchall()}
    assert {"is_deleted", "log_dir"} <= cols
    conn.close()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def test_migration_drops_strategy_groups_and_group_runs(tmp_path):
    """Phase 6.3: 旧库含 strategy_groups / group_runs 表 → migration 应 DROP 之。"""
    db = tmp_path / "legacy_with_groups.db"
    conn = sqlite3.connect(db)
    _create_legacy_schema(conn)
    conn.executescript(
        """
        CREATE TABLE strategy_groups (
            group_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            pipeline TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE group_runs (
            run_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    assert _table_exists(conn, "strategy_groups")
    assert _table_exists(conn, "group_runs")

    run_merge_strategies_migration(conn)

    assert not _table_exists(conn, "strategy_groups")
    assert not _table_exists(conn, "group_runs")
    conn.close()


def test_migration_drop_groups_idempotent(tmp_path):
    """新库无 strategy_groups / group_runs → DROP IF EXISTS 不报错, 多次执行幂等。"""
    db = tmp_path / "fresh_no_groups.db"
    conn = sqlite3.connect(db)
    _create_legacy_schema(conn)
    # 不创建 strategy_groups / group_runs
    run_merge_strategies_migration(conn)
    run_merge_strategies_migration(conn)
    assert not _table_exists(conn, "strategy_groups")
    assert not _table_exists(conn, "group_runs")
    conn.close()
