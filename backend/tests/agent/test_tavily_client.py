"""TavilyClient 测试 — cache hit/miss/expired/no_key/network_error。"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import pytest

from backend.services.agent.core.tavily_client import TavilyClient


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "tavily_cache"


def _fake_response(results: list[dict], answer: str = "summary") -> dict:
    return {
        "answer": answer,
        "results": results,
        "query": "q",
    }


def test_no_key_returns_none(cache_dir):
    c = TavilyClient(api_key=None, cache_dir=cache_dir)
    out = c.search_with_cache("000001", "industry", "x")
    assert out is None


def test_first_call_fetches_and_caches(cache_dir):
    c = TavilyClient(api_key="fake", cache_dir=cache_dir)

    fake = _fake_response([{"title": "T1", "content": "C1", "url": "u1"}])

    with patch.object(c, "_search", return_value=fake) as mock:
        out = c.search_with_cache("000001", "industry", "宁德时代 行业")
    assert mock.call_count == 1
    assert out is not None
    assert out["results"][0]["title"] == "T1"
    # 文件落盘
    p = cache_dir / "000001_industry.json"
    assert p.exists()


def test_second_call_within_ttl_uses_cache(cache_dir):
    c = TavilyClient(api_key="fake", cache_dir=cache_dir)
    fake = _fake_response([{"title": "T", "content": "C", "url": "u"}])

    with patch.object(c, "_search", return_value=fake) as mock:
        c.search_with_cache("000001", "industry", "q")
        c.search_with_cache("000001", "industry", "q")
    assert mock.call_count == 1


def test_expired_cache_refetches(cache_dir):
    c = TavilyClient(api_key="fake", cache_dir=cache_dir, ttl_days=7)
    with patch.object(c, "_search", return_value=_fake_response([{"title": "old"}])):
        c.search_with_cache("000001", "industry", "q")

    p = cache_dir / "000001_industry.json"
    old = time.time() - 8 * 86400
    os.utime(p, (old, old))

    with patch.object(
        c, "_search", return_value=_fake_response([{"title": "new"}])
    ) as mock:
        out = c.search_with_cache("000001", "industry", "q")
    assert mock.call_count == 1
    assert out["results"][0]["title"] == "new"


def test_network_error_falls_back_to_existing_cache(cache_dir):
    c = TavilyClient(api_key="fake", cache_dir=cache_dir)
    # 先建一个老缓存
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / "000001_industry.json"
    p.write_text(json.dumps(_fake_response([{"title": "stale"}])), encoding="utf-8")
    old = time.time() - 8 * 86400
    os.utime(p, (old, old))

    with patch.object(c, "_search", side_effect=RuntimeError("net down")):
        out = c.search_with_cache("000001", "industry", "q")
    assert out is not None
    assert out["results"][0]["title"] == "stale"


def test_network_error_no_cache_returns_none(cache_dir):
    c = TavilyClient(api_key="fake", cache_dir=cache_dir)
    with patch.object(c, "_search", side_effect=RuntimeError("net down")):
        out = c.search_with_cache("000001", "industry", "q")
    assert out is None


def test_different_sections_use_separate_caches(cache_dir):
    c = TavilyClient(api_key="fake", cache_dir=cache_dir)
    with patch.object(
        c,
        "_search",
        side_effect=[
            _fake_response([{"title": "ind"}]),
            _fake_response([{"title": "esg"}]),
        ],
    ):
        a = c.search_with_cache("000001", "industry", "q1")
        b = c.search_with_cache("000001", "esg", "q2")
    assert a["results"][0]["title"] == "ind"
    assert b["results"][0]["title"] == "esg"
