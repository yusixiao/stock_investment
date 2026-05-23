"""问股期 1 — Task 12:agent 路由骨架。

- GET  /api/v1/agent/skills            期 1 暂返空数组(前端兼容)
- GET  /api/v1/agent/sessions          列出 chat_sessions(按 last_active DESC)
- GET  /api/v1/agent/sessions/{sid}    懒创建 + 返回 session 元信息
- DELETE /api/v1/agent/sessions/{sid}  级联删除消息
- GET  /api/v1/agent/sessions/{sid}/messages  按 created_at ASC 列消息

_conn() 每次请求从 env 读 DSA_PORTFOLIO_DB,且确保 chat_* 表已建。
"""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter

from services.agent.session_repo import SessionRepo
from services.db_schema import init_chat_tables

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def _conn() -> sqlite3.Connection:
    path = os.environ.get("DSA_PORTFOLIO_DB", "data/portfolio.db")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    init_chat_tables(conn)
    return conn


def _repo() -> SessionRepo:
    return SessionRepo(_conn())


@router.get("/skills")
def get_skills():
    # 期 1 无独立技能概念(agent 通过 harness registry 暴露,前端暂不消费)
    return {"skills": []}


@router.get("/sessions")
def list_sessions(limit: int = 50):
    return {"items": _repo().list_sessions(limit=limit)}


@router.get("/sessions/{sid}")
def get_session(sid: str):
    repo = _repo()
    repo.upsert(sid)
    return repo.get(sid)


@router.delete("/sessions/{sid}")
def delete_session(sid: str):
    _repo().delete(sid)
    return {"ok": True}


@router.get("/sessions/{sid}/messages")
def list_messages(sid: str):
    return {"items": _repo().list_messages(sid)}
