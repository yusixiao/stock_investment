"""集中管理所有 SQLite DDL — 避免 TaskManager/GroupManager 中重复定义表结构。"""

import sqlite3


def init_backtest_tables(conn: sqlite3.Connection):
    """创建回测相关表: backtest_tasks, strategy_groups, group_runs, stock_exclusions。

    建表后调用 run_merge_strategies_migration() 做幂等列添加 + 数据迁移。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS backtest_tasks (
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
            deleted INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            log_dir TEXT
        );

        CREATE TABLE IF NOT EXISTS strategy_groups (
            group_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            pipeline TEXT NOT NULL,
            join_modes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        );

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
            initial_capital REAL NOT NULL DEFAULT 1000000,
            FOREIGN KEY (group_id) REFERENCES strategy_groups(group_id)
        );

        CREATE TABLE IF NOT EXISTS stock_exclusions (
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, symbol)
        );
    """)
    conn.commit()
    run_merge_strategies_migration(conn)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # row[1] 为列名 (sqlite3.Row 兼容索引访问)
    return any(
        (r[1] if not isinstance(r, sqlite3.Row) else r["name"]) == column for r in rows
    )


def run_merge_strategies_migration(conn: sqlite3.Connection):
    """Phase 4.7 (D6) 迁移: 添加 is_deleted / log_dir 列, 重写旧 pipeline_info。

    幂等: 检查列是否存在再 ALTER;pipeline_info 迁移仅对匹配旧形态的行执行。
    """
    # 1. is_deleted (老库 deleted 列已存在;新库已在建表 SQL 里加了)
    if not _column_exists(conn, "backtest_tasks", "is_deleted"):
        conn.execute(
            "ALTER TABLE backtest_tasks ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
        )
        # 同步遗留 deleted 列
        if _column_exists(conn, "backtest_tasks", "deleted"):
            conn.execute(
                "UPDATE backtest_tasks SET is_deleted = deleted WHERE deleted = 1"
            )

    # 2. log_dir
    if not _column_exists(conn, "backtest_tasks", "log_dir"):
        conn.execute("ALTER TABLE backtest_tasks ADD COLUMN log_dir TEXT")

    # 3. pipeline_info 旧格式 -> 新格式 (仅迁移含 $.pipeline 数组的行)
    conn.execute(
        """
        UPDATE backtest_tasks
        SET pipeline_info = json_object(
            'strategy_class', json_extract(pipeline_info, '$.pipeline[0].class_name'),
            'params', json_extract(pipeline_info, '$.pipeline[0].params')
        )
        WHERE pipeline_info IS NOT NULL
          AND json_extract(pipeline_info, '$.pipeline') IS NOT NULL
        """
    )
    conn.commit()
