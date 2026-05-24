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


# ===== Task 6: SessionRepo CRUD =====

import time

from services.agent.core.session_repo import SessionRepo


def _conn(tmp_path: Path):
    db = tmp_path / "p.db"
    c = sqlite3.connect(db)
    init_chat_tables(c)
    return c


def test_upsert_creates_session(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1", title="hello")
    s = repo.get("sid-1")
    assert s is not None
    assert s["session_id"] == "sid-1"
    assert s["title"] == "hello"
    assert s["status"] == "idle"
    assert s["msg_count"] == 0


def test_upsert_idempotent(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.upsert("sid-1")
    assert repo.get("sid-1") is not None


def test_upsert_preserves_title_when_empty(tmp_path: Path):
    """二次 upsert 不传 title 不应清空已有 title。"""
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1", title="hello")
    repo.upsert("sid-1")  # 默认 title=""
    s = repo.get("sid-1")
    assert s["title"] == "hello"


def test_update_status(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.update_status("sid-1", status="running", current_phase="phase1")
    s = repo.get("sid-1")
    assert s["status"] == "running"
    assert s["current_phase"] == "phase1"


def test_append_message_increments_msg_count(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.append_message("sid-1", role="user", content="分析比亚迪")
    repo.append_message(
        "sid-1",
        role="assistant",
        content="好的",
        thinking=[{"type": "thinking", "content": "x"}],
    )
    s = repo.get("sid-1")
    assert s["msg_count"] == 2
    msgs = repo.list_messages("sid-1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["thinking"] == [{"type": "thinking", "content": "x"}]


def test_list_messages_decodes_json_fields(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.append_message(
        "sid-1",
        role="assistant",
        content="ok",
        artifacts=[{"name": "r.md", "url": "/x"}],
        context={"phase": "p3"},
    )
    msgs = repo.list_messages("sid-1")
    assert msgs[0]["artifacts"] == [{"name": "r.md", "url": "/x"}]
    assert msgs[0]["context"] == {"phase": "p3"}


def test_list_sessions_orders_by_last_active(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("a")
    time.sleep(0.01)  # 确保 last_active 序差异
    repo.upsert("b")
    time.sleep(0.01)
    repo.append_message("a", role="user", content="hi")  # bumps a's last_active
    items = repo.list_sessions(limit=10)
    assert items[0]["session_id"] == "a"


def test_delete_cascade(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    repo.upsert("sid-1")
    repo.append_message("sid-1", role="user", content="x")
    repo.delete("sid-1")
    assert repo.get("sid-1") is None
    assert repo.list_messages("sid-1") == []


def test_get_nonexistent_returns_none(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    assert repo.get("nonexistent") is None


def test_list_sessions_pagination(tmp_path: Path):
    repo = SessionRepo(_conn(tmp_path))
    for i in range(5):
        repo.upsert(f"s{i}")
        time.sleep(0.005)
    page1 = repo.list_sessions(limit=2, offset=0)
    page2 = repo.list_sessions(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # 不重叠
    ids1 = {s["session_id"] for s in page1}
    ids2 = {s["session_id"] for s in page2}
    assert not (ids1 & ids2)
