"""DuckDB lifespan health check 测试。"""

from pathlib import Path

import pandas as pd
import pytest

from services.market_data import duckdb_store


@pytest.fixture
def reset_store():
    """每个用例前后清空全局 store，避免污染。"""
    duckdb_store.shutdown_duckdb()
    yield
    duckdb_store.shutdown_duckdb()


def _write_parquet(path: Path, df: pd.DataFrame):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_health_check_fails_when_daily_empty(tmp_path, monkeypatch, reset_store):
    """A 股 daily 目录不存在或为空 → 抛 RuntimeError。"""
    monkeypatch.setattr(duckdb_store, "MARKET_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="v_a_daily"):
        duckdb_store.init_duckdb_with_health_check()


def test_health_check_fails_when_adjust_factor_empty(
    tmp_path, monkeypatch, reset_store
):
    """daily 有数据但 adjust_factor 为空 → 抛 RuntimeError。"""
    daily_dir = tmp_path / "A" / "daily"
    _write_parquet(
        daily_dir / "000001.parquet",
        pd.DataFrame(
            {
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000.0],
                "amount": [10500.0],
            }
        ),
    )
    # adjust_factor 目录存在但无 parquet：视图无法创建 → 应抛错
    (tmp_path / "A" / "adjust_factor").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(duckdb_store, "MARKET_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="v_a_adjust_factor"):
        duckdb_store.init_duckdb_with_health_check()


def test_health_check_passes_with_real_data(reset_store):
    """真实 MARKET_DIR(若有数据)能通过；否则跳过。"""
    from config import MARKET_DIR

    a_daily = MARKET_DIR / "A" / "daily"
    a_adj = MARKET_DIR / "A" / "adjust_factor"
    if not (a_daily.exists() and any(a_daily.glob("*.parquet"))):
        pytest.skip("无真实 A/daily parquet 数据")
    if not (a_adj.exists() and any(a_adj.glob("*.parquet"))):
        pytest.skip("无真实 A/adjust_factor parquet 数据")

    # 不应抛错
    duckdb_store.init_duckdb_with_health_check()


def test_health_check_passes_with_fixture_data(tmp_path, monkeypatch, reset_store):
    """构造完整 fixture 数据 → 健康检查通过。"""
    daily_dir = tmp_path / "A" / "daily"
    adj_dir = tmp_path / "A" / "adjust_factor"
    _write_parquet(
        daily_dir / "000001.parquet",
        pd.DataFrame(
            {
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "volume": [1000.0],
                "amount": [10500.0],
            }
        ),
    )
    _write_parquet(
        adj_dir / "000001.parquet",
        pd.DataFrame({"date": ["2024-01-02"], "factor": [1.0]}),
    )
    monkeypatch.setattr(duckdb_store, "MARKET_DIR", tmp_path)
    duckdb_store.init_duckdb_with_health_check()
    store = duckdb_store.get_store()
    assert "000001" in store.list_symbols("A")
