"""routers/system_config.py 集成测试。

_store() 每次请求都从 env 读 DSA_CONFIG_PATH,所以只需在请求前设置 env。
"""

from fastapi.testclient import TestClient

from main import app
from services.system_config.field_schema import MASK_TOKEN


def test_get_returns_empty_initially(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.get("/api/v1/system/config")
    assert r.status_code == 200
    body = r.json()
    # 仍然兼容旧调用(不带 include_schema)— 至少返回 items 列表
    assert "items" in body
    # 即使 yaml 为空,schema 声明的 9 个字段也应该出现(value="")
    keys = {it["key"] for it in body["items"]}
    assert "LLM_OPENROUTER_API_KEY" in keys
    assert "TAVILY_API_KEY" in keys
    assert "LLM_DEFAULT_CHANNEL" in keys


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


def test_get_with_include_schema_returns_full_response(tmp_path, monkeypatch):
    """GET ?include_schema=true 返回完整 SystemConfigResponse:
    items + configVersion + maskToken + schema(categories)。"""
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    c.put(
        "/api/v1/system/config",
        json={
            "items": [
                {"key": "LLM_OPENROUTER_API_KEY", "value": "sk-secret"},
                {"key": "LLM_OPENROUTER_MODEL", "value": "gpt-oss"},
                {"key": "TAVILY_API_KEY", "value": "tvly-x"},
            ]
        },
    )
    r = c.get("/api/v1/system/config?include_schema=true")
    assert r.status_code == 200
    body = r.json()
    assert "config_version" in body
    assert "mask_token" in body
    assert body["mask_token"] == MASK_TOKEN
    assert "items" in body
    # 敏感字段已遮掩
    by_key = {it["key"]: it for it in body["items"]}
    assert by_key["LLM_OPENROUTER_API_KEY"]["value"] == MASK_TOKEN
    assert by_key["LLM_OPENROUTER_API_KEY"]["is_masked"] is True
    assert by_key["TAVILY_API_KEY"]["value"] == MASK_TOKEN
    # 非敏感字段原样返回
    assert by_key["LLM_OPENROUTER_MODEL"]["value"] == "gpt-oss"


def test_get_schema_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.get("/api/v1/system/config/schema")
    assert r.status_code == 200
    body = r.json()
    assert "schema_version" in body
    assert "categories" in body
    cats = {c["category"] for c in body["categories"]}
    assert {"ai_model", "data_source"} <= cats


def test_put_preserves_masked_sensitive_value(tmp_path, monkeypatch):
    """PUT 时若敏感字段值是 MASK_TOKEN,保留 yaml 现有值,不当成新值写入。"""
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    # 1. 先种入真实 key
    c.put(
        "/api/v1/system/config",
        json={"items": [{"key": "LLM_OPENROUTER_API_KEY", "value": "sk-real"}]},
    )
    # 2. 再次 PUT,API_KEY 字段传 MASK_TOKEN(模拟前端从 GET 拿到再原样回传)
    r = c.put(
        "/api/v1/system/config",
        json={
            "items": [
                {"key": "LLM_OPENROUTER_API_KEY", "value": MASK_TOKEN},
                {"key": "LLM_OPENROUTER_MODEL", "value": "new-model"},
            ]
        },
    )
    assert r.status_code == 200
    # 3. 取回原始(非遮掩)— 用 ConfigStore 直接读 yaml 验证真实落盘值
    from services.system_config.store import ConfigStore

    raw_kv = ConfigStore(tmp_path / "cfg.yaml").load()
    assert raw_kv["LLM_OPENROUTER_API_KEY"] == "sk-real"  # 保留
    assert raw_kv["LLM_OPENROUTER_MODEL"] == "new-model"  # 更新


def test_put_allows_clearing_sensitive_value(tmp_path, monkeypatch):
    """显式传空字符串应能清空敏感字段(区别于 MASK_TOKEN 的「保留」语义)。"""
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    c.put(
        "/api/v1/system/config",
        json={"items": [{"key": "LLM_OPENROUTER_API_KEY", "value": "sk-real"}]},
    )
    c.put(
        "/api/v1/system/config",
        json={"items": [{"key": "LLM_OPENROUTER_API_KEY", "value": ""}]},
    )
    from services.system_config.store import ConfigStore

    raw_kv = ConfigStore(tmp_path / "cfg.yaml").load()
    assert raw_kv.get("LLM_OPENROUTER_API_KEY", "") == ""


def test_put_returns_new_config_version(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.put(
        "/api/v1/system/config",
        json={"items": [{"key": "LLM_OPENROUTER_MODEL", "value": "m1"}]},
    )
    body = r.json()
    assert "config_version" in body
    v1 = body["config_version"]
    # 改后版本应变化
    r = c.put(
        "/api/v1/system/config",
        json={"items": [{"key": "LLM_OPENROUTER_MODEL", "value": "m2"}]},
    )
    v2 = r.json()["config_version"]
    assert v1 != v2


def test_validate_returns_valid_for_good_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.post(
        "/api/v1/system/config/validate",
        json={"items": [{"key": "LLM_OPENROUTER_MODEL", "value": "gpt-oss"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["issues"] == []


def test_validate_returns_issues_for_bad_default_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    r = c.post(
        "/api/v1/system/config/validate",
        json={"items": [{"key": "LLM_DEFAULT_CHANNEL", "value": "NONEXIST"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert len(body["issues"]) >= 1
    assert body["issues"][0]["severity"] == "error"


def test_validate_treats_mask_token_as_keep(tmp_path, monkeypatch):
    """MASK_TOKEN 在 validate 阶段应解掩为现有值,不应触发 channel 缺失误报。"""
    monkeypatch.setenv("DSA_CONFIG_PATH", str(tmp_path / "cfg.yaml"))
    c = TestClient(app)
    c.put(
        "/api/v1/system/config",
        json={
            "items": [
                {"key": "LLM_OPENROUTER_PROVIDER", "value": "openrouter"},
                {"key": "LLM_OPENROUTER_API_KEY", "value": "sk-real"},
                {"key": "LLM_OPENROUTER_MODEL", "value": "m"},
                {"key": "LLM_OPENROUTER_BASE_URL", "value": "u"},
                {"key": "LLM_DEFAULT_CHANNEL", "value": "OPENROUTER"},
            ]
        },
    )
    r = c.post(
        "/api/v1/system/config/validate",
        json={"items": [{"key": "LLM_OPENROUTER_API_KEY", "value": MASK_TOKEN}]},
    )
    assert r.json()["valid"] is True


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
