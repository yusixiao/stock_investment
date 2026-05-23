"""问股期 1 — Task 12:agent 路由骨架(skills + sessions CRUD,无 stream)。

每个测试用 monkeypatch 设 DSA_PORTFOLIO_DB,_conn() 每次请求都从 env 读路径。
"""

from fastapi.testclient import TestClient

from main import app


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
