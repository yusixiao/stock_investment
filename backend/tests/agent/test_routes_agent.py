"""问股期 1 — Task 12/18:agent 路由(skills + sessions CRUD + /chat/stream)。

每个测试用 monkeypatch 设 DSA_PORTFOLIO_DB,_conn() 每次请求都从 env 读路径。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from fastapi.testclient import TestClient

from main import app
from services.system_config.llm_client import CompletionResult


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_PORTFOLIO_DB", str(tmp_path / "p.db"))
    return TestClient(app)


def test_skills_returns_empty_array(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/skills")
    assert r.status_code == 200
    assert r.json() == {"skills": []}


def test_sessions_empty_initially(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/sessions")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_session_upsert_via_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/agent/sessions/sid-1")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "sid-1"

    r = c.get("/api/v1/agent/sessions/sid-1/messages")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_session_delete(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.get("/api/v1/agent/sessions/sid-1")
    r = c.delete("/api/v1/agent/sessions/sid-1")
    assert r.status_code == 200

    r = c.get("/api/v1/agent/sessions")
    assert r.json() == {"items": []}


def test_sessions_list_after_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.get("/api/v1/agent/sessions/sid-a")
    c.get("/api/v1/agent/sessions/sid-b")
    r = c.get("/api/v1/agent/sessions")
    items = r.json()["items"]
    ids = {it["session_id"] for it in items}
    assert ids == {"sid-a", "sid-b"}


# ===== Task 18:/chat/stream =====


def _setup_chat_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_PORTFOLIO_DB", str(tmp_path / "p.db"))
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    monkeypatch.setenv("DSA_AGENT_RUNS", str(tmp_path / "runs"))
    (tmp_path / "cfg.yaml").write_text(
        yaml.safe_dump(
            {
                "LLM_X_PROVIDER": "openai",
                "LLM_X_BASE_URL": "https://x",
                "LLM_X_API_KEY": "k",
                "LLM_X_MODEL": "m",
                "LLM_DEFAULT_CHANNEL": "X",
            }
        ),
        encoding="utf-8",
    )


def test_chat_stream_chitchat(tmp_path, monkeypatch):
    _setup_chat_env(tmp_path, monkeypatch)

    fake = MagicMock()
    fake.complete = AsyncMock(
        return_value=CompletionResult(text="你好!", tokens_in=3, tokens_out=2)
    )
    with patch("routers.agent.build_client_for_phase", return_value=fake):
        c = TestClient(app)
        with c.stream(
            "POST",
            "/api/v1/agent/chat/stream",
            json={
                "message": "你好",
                "session_id": "s1",
                "skills": [],
                "context": None,
            },
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    types = [e["type"] for e in events]
    assert types[0] == "thinking"
    assert types[-1] == "done"
    assert events[-1]["content"] == "你好!"


def test_chat_stream_persists_user_message(tmp_path, monkeypatch):
    _setup_chat_env(tmp_path, monkeypatch)

    fake = MagicMock()
    fake.complete = AsyncMock(
        return_value=CompletionResult(text="ok", tokens_in=1, tokens_out=1)
    )
    with patch("routers.agent.build_client_for_phase", return_value=fake):
        c = TestClient(app)
        with c.stream(
            "POST",
            "/api/v1/agent/chat/stream",
            json={"message": "hello world", "session_id": "sx"},
        ) as r:
            for _ in r.iter_lines():
                pass
        # 用户消息应当落库
        msgs = c.get("/api/v1/agent/sessions/sx/messages").json()["items"]
    roles = [m["role"] for m in msgs]
    contents = [m["content"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles
    assert "hello world" in contents
    assert "ok" in contents
