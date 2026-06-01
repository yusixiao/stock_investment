"""港股通成分股 MVP 测试 — adapter / updater / Context.is_hk_connect。"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest


# ===== adapter 分页 + 去重 =====


def _fake_page(codes_names, status=0):
    """构造 EastMoney push2 风格响应。"""
    diff = {str(i): {"f12": c, "f14": n} for i, (c, n) in enumerate(codes_names)}
    return {"rc": 0, "data": {"diff": diff} if codes_names else {}}


def test_adapter_fetch_hk_connect_paginates_and_dedups():
    from backend.adapters.eastmoney_adapter import EastMoneyAdapter

    page1 = _fake_page([("09988", "阿里巴巴-W"), ("00700", "腾讯控股")])
    page2 = _fake_page([("00700", "腾讯控股"), ("00005", "汇丰控股")])  # 00700 重
    page3 = _fake_page([])  # 空 → 终止

    class FakeResp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    responses = [FakeResp(page1), FakeResp(page2), FakeResp(page3)]

    with patch("backend.adapters.eastmoney_adapter.requests.Session") as mock_session:
        sess = mock_session.return_value
        sess.headers = {}
        sess.get.side_effect = responses
        with patch("backend.adapters.eastmoney_adapter.time.sleep"):
            members = EastMoneyAdapter().fetch_hk_connect_members()

    assert [m["code"] for m in members] == ["09988", "00700", "00005"]
    assert all(set(m.keys()) == {"code", "name"} for m in members)


def test_adapter_returns_empty_on_persistent_error():
    from backend.adapters.eastmoney_adapter import EastMoneyAdapter

    with patch("backend.adapters.eastmoney_adapter.requests.Session") as mock_session:
        sess = mock_session.return_value
        sess.headers = {}
        sess.get.side_effect = RuntimeError("network down")
        with patch("backend.adapters.eastmoney_adapter.time.sleep"):
            members = EastMoneyAdapter().fetch_hk_connect_members()

    assert members == []


# ===== updater append + dedup =====


@pytest.fixture
def isolated_market_dir(tmp_path, monkeypatch):
    """重定向 MARKET_DIR 到 tmp,确保测试间互不污染。"""
    monkeypatch.setattr("backend.config.MARKET_DIR", tmp_path)
    monkeypatch.setattr("backend.services.hk_connect_updater.MARKET_DIR", tmp_path)
    # 同时清缓存
    from backend.services import hk_connect_updater

    hk_connect_updater.invalidate_cache()
    yield tmp_path
    hk_connect_updater.invalidate_cache()


def test_updater_writes_and_dedups(isolated_market_dir):
    from backend.services import hk_connect_updater

    fake_members = [
        {"code": "09988", "name": "阿里巴巴-W"},
        {"code": "00700", "name": "腾讯控股"},
    ]
    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=fake_members,
    ):
        r1 = hk_connect_updater.fetch_and_save_hk_connect(as_of="2026-05-26")
        # 同日同板块再写,应去重而不是翻倍
        r2 = hk_connect_updater.fetch_and_save_hk_connect(as_of="2026-05-26")

    assert r1["count"] == 2
    assert r2["total_rows"] == 2  # 去重后还是 2 行

    df = pd.read_parquet(
        isolated_market_dir / "HK" / "membership" / "hk_connect.parquet"
    )
    assert set(df["code"]) == {"09988", "00700"}
    assert set(df.columns) == {"as_of_date", "code", "name", "board"}


def test_updater_appends_new_snapshot(isolated_market_dir):
    from backend.services import hk_connect_updater

    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=[{"code": "09988", "name": "阿里巴巴-W"}],
    ):
        hk_connect_updater.fetch_and_save_hk_connect(as_of="2026-05-19")

    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=[
            {"code": "09988", "name": "阿里巴巴-W"},
            {"code": "00700", "name": "腾讯控股"},
        ],
    ):
        hk_connect_updater.fetch_and_save_hk_connect(as_of="2026-05-26")

    codes = hk_connect_updater.get_latest_hk_connect_codes()
    # 只看最新日期 2026-05-26 的快照
    assert codes == {"09988", "00700"}


def test_updater_empty_fetch_does_not_crash(isolated_market_dir):
    """push2 + datacenter-web fallback 都失败时优雅返 count=0,不抛异常。"""
    from backend.services import hk_connect_updater

    with (
        patch.object(
            hk_connect_updater.EastMoneyAdapter,
            "fetch_hk_connect_members",
            return_value=[],
        ),
        patch.object(
            hk_connect_updater.EastMoneyAdapter,
            "fetch_hk_connect_members_holdrank",
            return_value=[],
        ),
    ):
        result = hk_connect_updater.fetch_and_save_hk_connect()

    assert result["count"] == 0


def test_updater_falls_back_to_holdrank_when_push2_blocked(isolated_market_dir):
    """push2 返空时自动切换 datacenter-web,确保 IP 限流下 MVP 仍能拉数据。"""
    from backend.services import hk_connect_updater

    with (
        patch.object(
            hk_connect_updater.EastMoneyAdapter,
            "fetch_hk_connect_members",
            return_value=[],
        ),
        patch.object(
            hk_connect_updater.EastMoneyAdapter,
            "fetch_hk_connect_members_holdrank",
            return_value=[
                {"code": "09988", "name": "阿里巴巴-W"},
                {"code": "00700", "name": "腾讯控股"},
            ],
        ) as mock_fallback,
    ):
        result = hk_connect_updater.fetch_and_save_hk_connect()

    assert result["count"] == 2
    assert mock_fallback.call_count == 1
    assert hk_connect_updater.get_latest_hk_connect_codes() == {"09988", "00700"}


def test_get_latest_codes_no_parquet(isolated_market_dir):
    from backend.services import hk_connect_updater

    assert hk_connect_updater.get_latest_hk_connect_codes() == set()


# ===== Context.is_hk_connect =====


def test_is_hk_connect_non_hk_symbol(isolated_market_dir):
    from backend.services import hk_connect_updater

    # 即便有快照,A/US 标的也应返回 False
    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=[{"code": "09988", "name": "阿里巴巴-W"}],
    ):
        hk_connect_updater.fetch_and_save_hk_connect()

    # 模拟 Context 行为(不依赖完整 market_data 构造)
    code = "000001.SZ".split(".")[0]
    assert code not in hk_connect_updater.get_latest_hk_connect_codes()


def test_is_hk_connect_hit_and_miss(isolated_market_dir):
    from backend.services import hk_connect_updater

    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=[
            {"code": "09988", "name": "阿里巴巴-W"},
            {"code": "00700", "name": "腾讯控股"},
        ],
    ):
        hk_connect_updater.fetch_and_save_hk_connect()

    codes = hk_connect_updater.get_latest_hk_connect_codes()
    # 命中
    assert "09988.HK".split(".")[0] in codes
    # 未命中(09992 泡泡玛特 2024 才纳入,这里没写入)
    assert "09992.HK".split(".")[0] not in codes


def test_cache_invalidates_on_write(isolated_market_dir):
    from backend.services import hk_connect_updater

    # 第一次写入 1 只
    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=[{"code": "09988", "name": "阿里巴巴-W"}],
    ):
        hk_connect_updater.fetch_and_save_hk_connect(as_of="2026-05-26")
    assert hk_connect_updater.get_latest_hk_connect_codes() == {"09988"}

    # 同日再写入扩大集合,缓存应失效返新集
    with patch.object(
        hk_connect_updater.EastMoneyAdapter,
        "fetch_hk_connect_members",
        return_value=[
            {"code": "09988", "name": "阿里巴巴-W"},
            {"code": "00700", "name": "腾讯控股"},
        ],
    ):
        hk_connect_updater.fetch_and_save_hk_connect(as_of="2026-05-26")
    assert hk_connect_updater.get_latest_hk_connect_codes() == {"09988", "00700"}
