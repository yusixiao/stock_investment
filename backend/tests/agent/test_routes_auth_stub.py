"""问股期 1 — Task 2:auth_stub 路由测试。

期 1 不实现真实鉴权,前端 AuthContext 期望永远收到 authEnabled: false。
"""

from fastapi.testclient import TestClient

from main import app


def test_auth_status_returns_disabled():
    client = TestClient(app)
    r = client.get("/api/v1/auth/status")
    assert r.status_code == 200
    assert r.json() == {"authEnabled": False}


def test_auth_status_method_get_only():
    client = TestClient(app)
    r = client.post("/api/v1/auth/status")
    # POST 应当 405(GET-only)
    assert r.status_code == 405
