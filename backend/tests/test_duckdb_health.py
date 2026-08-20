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


def test_health_check_passes_with_fixture_data(mini_market, reset_store):
    """完整的三市场 fixture 数据应通过健康检查。"""
    duckdb_store.init_duckdb_with_health_check()
    store = duckdb_store.get_store()
    assert "002594.SZ" in store.list_symbols("A")
