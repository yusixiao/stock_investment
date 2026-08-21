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

    # 先修复历史脏数据再建唯一索引。保留全部行，仅把确定性胜出的
    # 最小 task_id 保持 active，其余行降为 inactive，迁移可重复执行。
    if not _column_exists(conn, "backtest_tasks", "execution_account_id"):
        conn.execute(
            "ALTER TABLE backtest_tasks ADD COLUMN execution_account_id INTEGER"
        )
    if not _column_exists(conn, "backtest_tasks", "execution_status"):
        conn.execute(
            "ALTER TABLE backtest_tasks ADD COLUMN execution_status TEXT NOT NULL DEFAULT 'inactive'"
        )
    conn.execute(
        """
        UPDATE backtest_tasks
        SET execution_status = 'inactive', execution_account_id = NULL
        WHERE rowid IN (
            SELECT rowid FROM (
                SELECT rowid,
                       ROW_NUMBER() OVER (
                           PARTITION BY execution_account_id
                           ORDER BY task_id
                       ) AS row_number
                FROM backtest_tasks
                WHERE execution_status = 'active'
                  AND execution_account_id IS NOT NULL
            )
            WHERE row_number > 1
        )
        """
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


def init_portfolio_v1_tables(conn: sqlite3.Connection):
    """创建 Portfolio v1 账户及策略状态表；可与共享业务库重复执行。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS portfolio_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            base_currency TEXT NOT NULL,
            strategy_task_id TEXT UNIQUE,
            strategy_bound_at TEXT,
            strategy_unbound_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_account_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            tax REAL NOT NULL DEFAULT 0,
            realized_pnl REAL NOT NULL DEFAULT 0,
            trade_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_strategy_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            target_quantity INTEGER NOT NULL,
            reference_price REAL NOT NULL,
            status TEXT NOT NULL,
            effective_date TEXT NOT NULL,
            archived_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_strategy_target_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id) ON DELETE CASCADE,
            effective_date TEXT NOT NULL,
            targets TEXT NOT NULL,
            archived_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_strategy_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            state TEXT NOT NULL,
            payload TEXT,
            archived_at TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS portfolio_account_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES portfolio_accounts(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            cash REAL NOT NULL,
            market_value REAL NOT NULL,
            UNIQUE(account_id, date)
        );

        CREATE TABLE IF NOT EXISTS monitoring_strategy_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            strategy_class TEXT NOT NULL,
            filepath TEXT NOT NULL,
            params TEXT NOT NULL DEFAULT '{}',
            market TEXT NOT NULL,
            frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly')),
            symbols TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            next_run_date TEXT,
            last_run_at TEXT,
            last_run_status TEXT NOT NULL DEFAULT 'pending' CHECK (last_run_status IN ('pending', 'running', 'success', 'failed')),
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monitoring_strategy_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL REFERENCES monitoring_strategy_monitors(id),
            scheduled_date TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
            task_id TEXT,
            result TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS monitoring_stock_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            threshold_price REAL NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            state TEXT NOT NULL DEFAULT 'armed' CHECK (state IN ('armed', 'triggered', 'paused')),
            last_price REAL,
            last_price_date TEXT,
            last_triggered_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monitoring_stock_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL REFERENCES monitoring_stock_monitors(id),
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            observed_price REAL NOT NULL,
            threshold_price REAL NOT NULL,
            observed_date TEXT NOT NULL,
            triggered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded', 'notified'))
        );

        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(portfolio_account_trades)")}
    for name, definition in (("fee", "REAL NOT NULL DEFAULT 0"), ("tax", "REAL NOT NULL DEFAULT 0"), ("realized_pnl", "REAL NOT NULL DEFAULT 0")):
        if name not in columns:
            conn.execute(f"ALTER TABLE portfolio_account_trades ADD COLUMN {name} {definition}")
    _archive_duplicate_current_states(conn, "portfolio_strategy_targets")
    _archive_duplicate_current_states(conn, "portfolio_strategy_alerts")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_portfolio_account_trades_account
            ON portfolio_account_trades(account_id, trade_date, id);
        CREATE INDEX IF NOT EXISTS idx_portfolio_targets_account
            ON portfolio_strategy_targets(account_id, symbol);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_current_target
            ON portfolio_strategy_targets(account_id, symbol)
            WHERE archived_at IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_current_alert
            ON portfolio_strategy_alerts(account_id, symbol)
            WHERE archived_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_monitoring_strategy_runs_monitor
            ON monitoring_strategy_runs(monitor_id, scheduled_date DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_monitoring_stock_events_monitor
            ON monitoring_stock_events(monitor_id, observed_date DESC, id DESC);
        """
    )
    conn.commit()


def _archive_duplicate_current_states(conn: sqlite3.Connection, table: str):
    """保留每个账户/标的最新 current 行，其余行归档而非删除。"""
    if table not in {"portfolio_strategy_targets", "portfolio_strategy_alerts"}:
        raise ValueError(f"unsupported portfolio state table: {table}")
    conn.execute(
        f"""
        UPDATE {table}
        SET archived_at = CURRENT_TIMESTAMP
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY account_id, symbol
                           ORDER BY updated_at DESC, id DESC
                       ) AS row_number
                FROM {table}
                WHERE archived_at IS NULL
            )
            WHERE row_number > 1
        )
        """
    )
