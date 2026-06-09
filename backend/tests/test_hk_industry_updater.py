"""港股 industry updater 测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd


def test_to_yfinance_symbol_strips_leading_zero():
    from backend.services.hk_industry_updater import _to_yfinance_symbol

    assert _to_yfinance_symbol("09988") == "9988.HK"
    assert _to_yfinance_symbol("00700") == "0700.HK"
    assert _to_yfinance_symbol("00005") == "0005.HK"
    # 已带后缀:大写返回
    assert _to_yfinance_symbol("0700.hk") == "0700.HK"


def test_fetch_and_save_writes_parquet(tmp_path):
    """端到端:mock fetch_one,验证 parquet schema + 视图刷新调用。"""
    from backend.services import hk_industry_updater as mod

    fake_records = {
        "00700": {
            "code": "00700",
            "name": "Tencent Holdings",
            "sector": "Communication Services",
            "industry": "Internet Content & Information",
        },
        "09988": {
            "code": "09988",
            "name": "Alibaba Group",
            "sector": "Consumer Cyclical",
            "industry": "Internet Retail",
        },
    }

    def fake_fetch(code):
        return fake_records.get(code)

    target = tmp_path / "hk_industry.parquet"

    with patch.object(mod, "_parquet_path", return_value=target):
        with patch.object(
            mod,
            "get_latest_hk_connect_codes",
            return_value={"00700", "09988"},
        ):
            # 视图刷新 / stock_index 刷新都不应阻塞流程,即使失败
            with patch(
                "backend.services.duckdb_store.get_store",
                side_effect=RuntimeError("not initialized"),
            ):
                with patch(
                    "backend.services.stock_index.refresh_hk_industry",
                    side_effect=RuntimeError("not loaded"),
                ):
                    result = mod.fetch_and_save_hk_industry(
                        sleep_sec=0,
                        fetch_one_func=fake_fetch,
                    )

    assert result["fetched"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert result["total_rows"] == 2
    assert target.exists()

    df = pd.read_parquet(target)
    assert set(df.columns) == {"code", "name", "sector", "industry", "updated_at"}
    assert sorted(df["code"].tolist()) == ["00700", "09988"]
    # updated_at 是 ISO 字符串
    assert all(isinstance(x, str) and "T" in x for x in df["updated_at"])


def test_incremental_skips_fresh_records(tmp_path):
    """已存在且未过期的 code 跳过 fetch。"""
    from backend.services import hk_industry_updater as mod

    target = tmp_path / "hk_industry.parquet"

    # 预置一条 1 天前的新鲜记录
    fresh_iso = (
        (datetime.now(timezone.utc) - timedelta(days=1))
        .replace(microsecond=0)
        .isoformat()
    )
    pd.DataFrame(
        [
            {
                "code": "00700",
                "name": "Tencent Holdings",
                "sector": "Communication Services",
                "industry": "Internet Content & Information",
                "updated_at": fresh_iso,
            }
        ]
    ).to_parquet(target, index=False)

    fetch_calls = []

    def fake_fetch(code):
        fetch_calls.append(code)
        return {
            "code": code,
            "name": f"Name-{code}",
            "sector": "S",
            "industry": "I",
        }

    with patch.object(mod, "_parquet_path", return_value=target):
        with patch(
            "backend.services.duckdb_store.get_store",
            side_effect=RuntimeError(),
        ):
            with patch(
                "backend.services.stock_index.refresh_hk_industry",
                side_effect=RuntimeError(),
            ):
                result = mod.fetch_and_save_hk_industry(
                    codes={"00700", "09988"},
                    max_age_days=30,
                    sleep_sec=0,
                    fetch_one_func=fake_fetch,
                )

    # 00700 fresh -> skip;09988 不存在 -> fetch
    assert fetch_calls == ["09988"]
    assert result["fetched"] == 1
    assert result["skipped"] == 1
    assert result["total_rows"] == 2


def test_failed_fetch_does_not_block(tmp_path):
    """单只失败不影响整体落盘。"""
    from backend.services import hk_industry_updater as mod

    target = tmp_path / "hk_industry.parquet"

    def fake_fetch(code):
        if code == "00700":
            return {
                "code": "00700",
                "name": "Tencent",
                "sector": "Comm",
                "industry": "Internet",
            }
        return None  # 模拟拉取失败 / 空 info

    with patch.object(mod, "_parquet_path", return_value=target):
        with patch(
            "backend.services.duckdb_store.get_store",
            side_effect=RuntimeError(),
        ):
            with patch(
                "backend.services.stock_index.refresh_hk_industry",
                side_effect=RuntimeError(),
            ):
                result = mod.fetch_and_save_hk_industry(
                    codes={"00700", "00001", "00002"},
                    sleep_sec=0,
                    fetch_one_func=fake_fetch,
                )

    assert result["fetched"] == 1
    assert result["failed"] == 2
    assert result["total_rows"] == 1


def test_empty_hk_connect_returns_zero(tmp_path):
    """港股通名单为空时,直接 return 不抓数据。"""
    from backend.services import hk_industry_updater as mod

    target = tmp_path / "hk_industry.parquet"

    def fake_fetch(code):
        raise AssertionError("不应被调用")

    with patch.object(mod, "_parquet_path", return_value=target):
        with patch.object(mod, "get_latest_hk_connect_codes", return_value=set()):
            result = mod.fetch_and_save_hk_industry(
                sleep_sec=0,
                fetch_one_func=fake_fetch,
            )

    assert result["fetched"] == 0
    assert result["total_rows"] == 0
    assert not target.exists()


def test_stock_index_loads_hk_industry(tmp_path, monkeypatch):
    """stock_index.init_stock_index 启动时把 hk_industry parquet 内容回填到内存索引。"""
    from backend.services import stock_index

    # 构造假的目录结构
    data_root = tmp_path / "data"
    market = data_root / "market"
    hk_daily = market / "HK" / "daily"
    hk_daily.mkdir(parents=True)
    # 创建两个港股 daily 文件占位(只判断存在性)
    (hk_daily / "00700.parquet").write_bytes(b"")
    (hk_daily / "09988.parquet").write_bytes(b"")

    membership = market / "HK" / "membership"
    membership.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "code": "00700",
                "name": "Tencent",
                "sector": "Comm",
                "industry": "Internet Content & Information",
                "updated_at": "2026-06-01T00:00:00+00:00",
            }
        ]
    ).to_parquet(membership / "hk_industry.parquet", index=False)

    monkeypatch.setattr(stock_index, "MARKET_DIR", market)
    # A 股目录不存在:fallback 路径会跳过 A,只看 HK
    monkeypatch.setattr(stock_index, "BASIC_DIR", data_root / "basic" / "A")

    stock_index.init_stock_index()

    assert (
        stock_index.get_industry("00700", market="HK")
        == "Internet Content & Information"
    )
    # 09988 没在 hk_industry 中 → industry=None,但仍在索引(从 daily 文件名)
    assert stock_index.get_industry("09988", market="HK") is None
    assert stock_index.get_name("00700", market="HK") == "Tencent"
