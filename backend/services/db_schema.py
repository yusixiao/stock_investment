"""集中管理所有 SQLite DDL — 避免 TaskManager/GroupManager 中重复定义表结构。"""

import sqlite3


def init_backtest_tables(conn: sqlite3.Connection):
    """创建回测相关表: backtest_tasks, strategy_groups, group_runs, stock_exclusions。"""
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
            deleted INTEGER NOT NULL DEFAULT 0
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
