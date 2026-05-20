from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestStockRoutes:
    def test_list_stocks(self):
        resp = client.get("/api/stocks")
        assert resp.status_code == 200
        data = resp.json()
        assert "stocks" in data
        assert "total" in data

    def test_list_stocks_with_search(self):
        resp = client.get("/api/stocks?search=600028")
        assert resp.status_code == 200

    def test_list_stocks_with_pagination(self):
        resp = client.get("/api/stocks?page=1&page_size=10")
        assert resp.status_code == 200

    def test_get_kline(self):
        resp = client.get("/api/stocks/600028.SH/kline")
        assert resp.status_code in [200, 404]

    def test_get_kline_with_date_range(self):
        resp = client.get(
            "/api/stocks/600028.SH/kline?start_date=2026-04-01&end_date=2026-04-10"
        )
        assert resp.status_code in [200, 404]

    def test_get_indicators(self):
        resp = client.get("/api/stocks/600028.SH/indicators?types=ma,macd")
        assert resp.status_code in [200, 404]

    def test_get_kline_qfq(self):
        resp = client.get("/api/stocks/600028.SH/kline?adjust=qfq")
        assert resp.status_code in [200, 404]

    def test_get_indicators_qfq(self):
        resp = client.get("/api/stocks/600028.SH/indicators?types=ma&adjust=qfq")
        assert resp.status_code in [200, 404]


# /api/data/* 路由已下线(manual update 废弃),对应测试已移除
