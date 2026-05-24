"""问股期 1 — Task 12:agent 路由骨架。

- GET  /api/v1/agent/skills            期 1 暂返空数组(前端兼容)
- GET  /api/v1/agent/sessions          列出 chat_sessions(按 last_active DESC)
- GET  /api/v1/agent/sessions/{sid}    懒创建 + 返回 session 元信息
- DELETE /api/v1/agent/sessions/{sid}  级联删除消息
- GET  /api/v1/agent/sessions/{sid}/messages  按 created_at ASC 列消息

_conn() 每次请求从 env 读 DSA_PORTFOLIO_DB,且确保 chat_* 表已建。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import stock_index
from services.agent.core import sse
from services.agent.coordinator import Coordinator
from services.duckdb_store import get_store as get_duckdb_store
from services.agent.core.llm_routing import resolve_channel_name
from services.agent.core.session_repo import SessionRepo
from services.agent.core.tavily_client import TavilyClient
from services.agent.core.workspace import Workspace
from services.db_schema import init_chat_tables
from services.system_config.channels import get_channel
from services.system_config.llm_client import LLMError, build_client
from services.system_config.store import ConfigStore

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


# ===== Task 18:/chat/stream =====


class ChatStreamRequest(BaseModel):
    message: str
    session_id: str
    skills: list[str] = []
    context: Optional[dict] = None


def _config_kv() -> dict:
    path = Path(os.environ.get("DSA_CONFIG_PATH", "config/system_config.yaml"))
    return ConfigStore(path).load()


def build_client_for_phase(phase: str):
    """按 phase 解析 channel 并构造 LLMClient(供 Coordinator 注入)。"""
    kv = _config_kv()
    name = resolve_channel_name(kv, phase)
    ch = get_channel(kv, name)
    if not ch:
        raise LLMError("CONFIG", f"channel {name} not configured")
    return build_client(ch)


def _workspace() -> Workspace:
    return Workspace(Path(os.environ.get("DSA_AGENT_RUNS", "data/agent_runs")))


@router.post("/chat/stream")
async def chat_stream(payload: ChatStreamRequest = Body(...)):
    queue: asyncio.Queue = asyncio.Queue()

    async def sse_send(event: dict) -> None:
        await queue.put(sse.encode(event))

    repo = _repo()
    repo.upsert(payload.session_id)
    repo.append_message(
        payload.session_id,
        role="user",
        content=payload.message,
        context=payload.context,
    )

    # full_pipeline 走真实 DuckDB store;chitchat / qa_followup 不会用到
    try:
        store = get_duckdb_store()
    except Exception:
        store = None

    coord = Coordinator(
        sse_send=sse_send,
        repo=repo,
        workspace=_workspace(),
        stock_index=stock_index,
        llm_factory=build_client_for_phase,
        store=store,
        indicators=None,
        tavily=TavilyClient(api_key=_config_kv().get("TAVILY_API_KEY") or None),
    )

    async def runner() -> None:
        try:
            await coord.run(
                session_id=payload.session_id,
                message=payload.message,
                context=payload.context,
            )
        finally:
            await queue.put(None)

    async def gen():
        task = asyncio.create_task(runner())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream")
