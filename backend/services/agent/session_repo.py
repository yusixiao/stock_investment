"""问股期 1 / Task 6:chat_sessions / chat_messages 的 CRUD 封装。

设计要点:
- 构造器接收 sqlite3.Connection,不持有路径(便于测试注入临时 DB)
- 自动开启 PRAGMA foreign_keys=ON(级联删除依赖此项)
- ON CONFLICT upsert 保留已有 title(空 title 不覆盖)
- context / thinking / artifacts 三个 JSON 列由本类透明序列化/反序列化
- last_active 由本类自动更新(每次 upsert / update_status / append_message)
- msg_count 由 append_message 自增(避免上层手动维护)

不在本类范畴:
- 鉴权(期 1 单机模式无 user_id 概念)
- 事件流(SSE 由 routers 层处理)
- 工作目录管理(由 workspace.py 负责)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    """ISO8601 UTC,精度到微秒(供 last_active 排序)。"""
    return datetime.now(timezone.utc).isoformat()


class SessionRepo:
    """chat_sessions + chat_messages CRUD。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        # 开启外键级联(默认关闭),否则 ON DELETE CASCADE 不生效
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ===== Sessions =====

    def upsert(
        self,
        session_id: str,
        *,
        title: str = "",
        stock_code: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> None:
        """创建或更新 session。已存在时:
        - title 仅当传入非空才覆盖(NULLIF + COALESCE)
        - stock_code / output_dir 传 None 时保留旧值
        - last_active 总是刷新
        """
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO chat_sessions (session_id, title, stock_code, output_dir,
                                       status, current_phase, created_at,
                                       last_active, msg_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                title       = COALESCE(NULLIF(excluded.title, ''), chat_sessions.title),
                stock_code  = COALESCE(excluded.stock_code, chat_sessions.stock_code),
                output_dir  = COALESCE(excluded.output_dir, chat_sessions.output_dir),
                last_active = excluded.last_active
            """,
            (session_id, title, stock_code, output_dir, "idle", None, now, now, 0),
        )
        self.conn.commit()

    def get(self, session_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def update_status(
        self,
        session_id: str,
        *,
        status: Optional[str] = None,
        current_phase: Optional[str] = None,
    ) -> None:
        """部分更新 status / current_phase。同时刷新 last_active。"""
        sets: list[str] = []
        vals: list = []
        if status is not None:
            sets.append("status = ?")
            vals.append(status)
        if current_phase is not None:
            sets.append("current_phase = ?")
            vals.append(current_phase)
        sets.append("last_active = ?")
        vals.append(_now_iso())
        vals.append(session_id)
        self.conn.execute(
            f"UPDATE chat_sessions SET {', '.join(sets)} WHERE session_id = ?",
            vals,
        )
        self.conn.commit()

    def list_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        """按 last_active DESC 列出会话。"""
        cur = self.conn.execute(
            "SELECT * FROM chat_sessions ORDER BY last_active DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def delete(self, session_id: str) -> None:
        """删除会话及其全部消息(显式删消息以兼容未开 PRAGMA 的环境)。"""
        self.conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
        )
        self.conn.execute(
            "DELETE FROM chat_sessions WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()

    # ===== Messages =====

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        context: Optional[dict] = None,
        thinking: Optional[list] = None,
        artifacts: Optional[list] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ) -> str:
        """追加一条消息。返回新消息的 UUID。同时 msg_count++ 与 last_active 刷新。"""
        mid = str(uuid.uuid4())
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO chat_messages (id, session_id, role, content, context,
                                       thinking, artifacts, tokens_in, tokens_out,
                                       created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                session_id,
                role,
                content,
                json.dumps(context, ensure_ascii=False) if context else None,
                json.dumps(thinking, ensure_ascii=False) if thinking else None,
                json.dumps(artifacts, ensure_ascii=False) if artifacts else None,
                tokens_in,
                tokens_out,
                now,
            ),
        )
        self.conn.execute(
            """
            UPDATE chat_sessions
            SET msg_count = msg_count + 1, last_active = ?
            WHERE session_id = ?
            """,
            (now, session_id),
        )
        self.conn.commit()
        return mid

    def list_messages(self, session_id: str) -> list[dict]:
        """按 created_at ASC 列出消息。JSON 列自动反序列化。"""
        cur = self.conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        cols = [d[0] for d in cur.description]
        out: list[dict] = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            for k in ("context", "thinking", "artifacts"):
                if d.get(k):
                    d[k] = json.loads(d[k])
            out.append(d)
        return out
