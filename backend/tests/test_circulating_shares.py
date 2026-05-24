"""流通股数服务测试(2026-05-24:数据源切换到 DuckDB v_a_indicator)。"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from services.circulating_shares import (
    CIRCULATING_SHARES_FILE,
    get_circulating_shares,
    update_circulating_shares,
)


@pytest.fixture(autouse=True)
def clean_file(tmp_path, monkeypatch):
    """使用临时目录避免污染真实数据。"""
    test_file = tmp_path / "circulating_shares.parquet"
    monkeypatch.setattr(
        "services.circulating_shares.CIRCULATING_SHARES_FILE", test_file
    )
    yield test_file


def _mock_duckdb_df():
    return pd.DataFrame(
        {
            "SECURITY_CODE": ["600001", "600002", "000001"],
            "A_FREE_SHARE": [100_000_000, 200_000_000, 50_000_000.0],
        }
    )


@patch("services.duckdb_store.get_store")
def test_update_circulating_shares_from_duckdb(mock_get_store, clean_file):
    fake_store = MagicMock()
    fake_store._conn.execute.return_value.fetchdf.return_value = _mock_duckdb_df()
    mock_get_store.return_value = fake_store

    result = update_circulating_shares()

    assert result["count"] == 3
    assert "update_date" in result

    df = pd.read_parquet(clean_file)
    assert set(df.columns) == {"symbol", "circulating_shares", "update_date"}
    assert len(df) == 3
    assert df.loc[df["symbol"] == "600001", "circulating_shares"].iloc[0] == 100_000_000
    assert df.loc[df["symbol"] == "000001", "circulating_shares"].iloc[0] == 50_000_000


@patch("services.duckdb_store.get_store")
def test_update_raises_when_no_data(mock_get_store, clean_file):
    fake_store = MagicMock()
    fake_store._conn.execute.return_value.fetchdf.return_value = pd.DataFrame(
        columns=["SECURITY_CODE", "A_FREE_SHARE"]
    )
    mock_get_store.return_value = fake_store
    with pytest.raises(ValueError, match="A_FREE_SHARE"):
        update_circulating_shares()


@patch("services.duckdb_store.get_store")
def test_get_circulating_shares(mock_get_store, clean_file):
    fake_store = MagicMock()
    fake_store._conn.execute.return_value.fetchdf.return_value = _mock_duckdb_df()
    mock_get_store.return_value = fake_store
    update_circulating_shares()

    df = get_circulating_shares()
    assert df is not None
    assert len(df) == 3


def test_get_circulating_shares_no_file(clean_file):
    result = get_circulating_shares()
    assert result is None
