"""集中管理所有 SQLite DDL — 避免 TaskManager/GroupManager 中重复定义表结构。"""

import sqlite3


def init_market_refresh_tables(conn: sqlite3.Connection):
    """创建市场数据 refresh 生命周期表。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_refreshes (
            refresh_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error TEXT,
            market_states TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_market_refreshes_status
            ON market_refreshes(status);
        CREATE INDEX IF NOT EXISTS idx_market_refreshes_created_at
            ON market_refreshes(created_at DESC);
        CREATE TABLE IF NOT EXISTS market_refresh_versions (
            market TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def init_backtest_tables(conn: sqlite3.Connection):
    """创建回测相关表: backtest_tasks, stock_exclusions。

    建表后调用 run_merge_strategies_migration() 做幂等列添加 + 数据迁移
    + DROP 已废弃的 strategy_groups / group_runs(Phase 6.3)。
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
            log_dir TEXT,
            execution_account_id INTEGER,
            execution_status TEXT NOT NULL DEFAULT 'inactive'
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

    # 执行关联元数据；活动账户通过部分唯一索引保证一对一。
    if not _column_exists(conn, "backtest_tasks", "execution_account_id"):
        conn.execute(
            "ALTER TABLE backtest_tasks ADD COLUMN execution_account_id INTEGER"
        )
    if not _column_exists(conn, "backtest_tasks", "execution_status"):
        conn.execute(
            "ALTER TABLE backtest_tasks ADD COLUMN execution_status TEXT NOT NULL DEFAULT 'inactive'"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_backtest_active_execution_account "
        "ON backtest_tasks(execution_account_id) "
        "WHERE execution_status = 'active' AND execution_account_id IS NOT NULL"
    )

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

    # 4. DROP 已废弃的策略组表 (Phase 6.3, T6.3)
    # IF EXISTS 保证幂等 — 旧库有表则 DROP, 新库无表则跳过
    conn.execute("DROP TABLE IF EXISTS group_runs")
    conn.execute("DROP TABLE IF EXISTS strategy_groups")
    conn.commit()


def init_chat_tables(conn: sqlite3.Connection):
    """问股期 1 (Task 1):创建 chat_sessions / chat_messages 两表 + 索引。

    幂等:全部 IF NOT EXISTS。完整 CRUD 由 services/agent/session_repo.py 封装(Task 6)。

    chat_sessions  会话主表(一行 = 一个 chat session)
      - session_id    UUID(由路由生成)
      - title         显示标题(默认空,首次问完后由 coordinator 写入)
      - stock_code    本会话锚定的股票代码(可空,闲聊会话为 NULL)
      - output_dir    工作目录绝对路径(由 services/agent/workspace.py 分配,Task 7)
      - status        idle / running / done / error
      - current_phase 当前 phase(coordinator/chitchat/qa_followup/data_pack/phase3_quant/...)
      - created_at    ISO8601 字符串
      - last_active   ISO8601 字符串(每条消息后刷新)
      - msg_count     该会话消息总数(冗余便于列表排序展示)

    chat_messages  消息明细(append-only;artifacts/context/thinking 为 JSON 字符串)
      - id           UUID(由路由生成,前端透传)
      - session_id   外键 → chat_sessions.session_id(级联删除)
      - role         user / assistant / system
      - content      可见 markdown 文本
      - context      JSON:{ phase, agent_id, source_session_id, ... }
      - thinking     LLM thinking 文本(可选)
      - artifacts    JSON 数组:[{ type, path, ... }]
      - tokens_in    LLM 输入 token 数(可选)
      - tokens_out   LLM 输出 token 数(可选)
      - created_at   ISO8601
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id    TEXT PRIMARY KEY,
            title         TEXT NOT NULL DEFAULT '',
            stock_code    TEXT,
            output_dir    TEXT,
            status        TEXT NOT NULL DEFAULT 'idle',
            current_phase TEXT,
            created_at    TEXT NOT NULL,
            last_active   TEXT NOT NULL,
            msg_count     INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_last_active "
        "ON chat_sessions(last_active DESC)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            context    TEXT,
            thinking   TEXT,
            artifacts  TEXT,
            tokens_in  INTEGER,
            tokens_out INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session "
        "ON chat_messages(session_id, created_at)"
    )
    conn.commit()
