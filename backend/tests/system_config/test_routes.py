"""routers/system_config.py 集成测试。

_store() 每次请求都从 env 读 DSA_CONFIG_PATH,所以只需在请求前设置 env。
"""

from fastapi.testclient import TestClient

from main import app


def test_get_returns_empty_initially(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.get("/api/v1/system/config")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_put_then_get(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.put(
        "/api/v1/system/config",
        json={
            "items": [
                {"key": "LLM_DEEPSEEK_PROVIDER", "value": "deepseek"},
                {"key": "LLM_DEEPSEEK_API_KEY", "value": "sk-x"},
                {"key": "LLM_DEEPSEEK_MODEL", "value": "deepseek-chat"},
                {"key": "LLM_DEEPSEEK_BASE_URL", "value": "https://api.deepseek.com"},
                {"key": "LLM_DEFAULT_CHANNEL", "value": "DEEPSEEK"},
            ]
        },
    )
    assert r.status_code == 200
    r = c.get("/api/v1/system/config")
    items = {it["key"]: it["value"] for it in r.json()["items"]}
    assert items["LLM_DEEPSEEK_API_KEY"] == "sk-x"
    assert items["LLM_DEFAULT_CHANNEL"] == "DEEPSEEK"


def test_put_rejects_invalid_default_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.put(
        "/api/v1/system/config",
        json={"items": [{"key": "LLM_DEFAULT_CHANNEL", "value": "NONEXIST"}]},
    )
    assert r.status_code == 400
    assert "channel" in r.json()["detail"].lower()


def test_delete_one(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    c.put(
        "/api/v1/system/config",
        json={
            "items": [
                {"key": "LLM_X_PROVIDER", "value": "openai"},
                {"key": "LLM_X_API_KEY", "value": "k"},
                {"key": "LLM_X_MODEL", "value": "m"},
                {"key": "LLM_X_BASE_URL", "value": "u"},
            ]
        },
    )
    r = c.delete("/api/v1/system/config/LLM_X_API_KEY")
    assert r.status_code == 200
    r = c.get("/api/v1/system/config")
    keys = {it["key"] for it in r.json()["items"]}
    assert "LLM_X_API_KEY" not in keys
    assert "LLM_X_PROVIDER" in keys
