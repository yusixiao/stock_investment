"""问股期 1 — Task 1:chat_sessions / chat_messages schema 最小测试。

完整 CRUD 测试在 Task 6(session_repo)。
"""

import sqlite3
from pathlib import Path

from services.db_schema import init_chat_tables


def test_chat_sessions_table_exists(tmp_path: Path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    init_chat_tables(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_sessions'"
    )
    assert cur.fetchone() is not None
    cur = conn.execute("PRAGMA table_info(chat_sessions)")
    cols = {row[1] for row in cur.fetchall()}
    assert {
        "session_id",
        "title",
        "stock_code",
        "output_dir",
        "status",
        "current_phase",
        "created_at",
        "last_active",
        "msg_count",
    } <= cols
    conn.close()


def test_chat_messages_table_exists(tmp_path: Path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    init_chat_tables(conn)
    cur = conn.execute("PRAGMA table_info(chat_messages)")
    cols = {row[1] for row in cur.fetchall()}
    assert {
        "id",
        "session_id",
        "role",
        "content",
        "context",
        "thinking",
        "artifacts",
        "tokens_in",
        "tokens_out",
        "created_at",
    } <= cols
    conn.close()


def test_init_chat_tables_idempotent(tmp_path: Path):
    """调两次不应报错(IF NOT EXISTS 保证)。"""
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    init_chat_tables(conn)
    init_chat_tables(conn)
    conn.close()


def test_indexes_created(tmp_path: Path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    init_chat_tables(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name IN ('chat_sessions','chat_messages')"
    )
    names = {row[0] for row in cur.fetchall()}
    assert "idx_sessions_last_active" in names
    assert "idx_messages_session" in names
    conn.close()
