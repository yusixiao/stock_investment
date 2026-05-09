import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestStrategyGroupAPI:
    def test_create_group(self, client):
        body = {
            "name": "测试组",
            "pipeline": [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}}],
            "join_modes": [],
        }
        resp = client.post("/api/backtest/groups", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert "group_id" in data
        assert data["name"] == "测试组"

    def test_list_groups(self, client):
        body = {
            "name": "列表测试",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        client.post("/api/backtest/groups", json=body)
        resp = client.get("/api/backtest/groups")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_group(self, client):
        body = {
            "name": "详情测试",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]
        resp = client.get(f"/api/backtest/groups/{gid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "详情测试"

    def test_update_group(self, client):
        body = {
            "name": "旧名",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]
        resp = client.patch(f"/api/backtest/groups/{gid}", json={"name": "新名"})
        assert resp.status_code == 200
        get_resp = client.get(f"/api/backtest/groups/{gid}")
        assert get_resp.json()["name"] == "新名"

    def test_delete_group(self, client):
        body = {
            "name": "待删除",
            "pipeline": [{"filepath": "a.py", "class_name": "A"}],
            "join_modes": [],
        }
        create_resp = client.post("/api/backtest/groups", json=body)
        gid = create_resp.json()["group_id"]
        resp = client.delete(f"/api/backtest/groups/{gid}")
        assert resp.status_code == 200
        get_resp = client.get(f"/api/backtest/groups/{gid}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_group(self, client):
        resp = client.get("/api/backtest/groups/nonexistent")
        assert resp.status_code == 404
