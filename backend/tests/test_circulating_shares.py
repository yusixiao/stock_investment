"""流通股数服务测试。"""

import pandas as pd
import pytest
from unittest.mock import patch
from pathlib import Path

from services.circulating_shares import update_circulating_shares, get_circulating_shares, CIRCULATING_SHARES_FILE


@pytest.fixture(autouse=True)
def clean_file(tmp_path, monkeypatch):
    """使用临时目录避免污染真实数据。"""
    test_file = tmp_path / "circulating_shares.parquet"
    monkeypatch.setattr("services.circulating_shares.CIRCULATING_SHARES_FILE", test_file)
    yield test_file


def _mock_spot_data():
    return pd.DataFrame({
        "代码": ["600001", "600002", "600003"],
        "名称": ["测试A", "测试B", "测试C"],
        "最新价": [10.0, 20.0, 0.0],
        "流通市值": [1_000_000_000, 2_000_000_000, 0],
        "总市值": [2_000_000_000, 3_000_000_000, 0],
    })


@patch("services.circulating_shares.ak.stock_zh_a_spot_em")
def test_update_circulating_shares(mock_api, clean_file):
    mock_api.return_value = _mock_spot_data()
    result = update_circulating_shares()

    assert result["count"] == 2  # 600003 被过滤（价格和流通市值为0）
    assert "update_date" in result

    df = pd.read_parquet(clean_file)
    assert set(df.columns) == {"symbol", "circulating_shares", "update_date"}
    assert len(df) == 2

    row_a = df[df["symbol"] == "600001"].iloc[0]
    assert row_a["circulating_shares"] == 100_000_000  # 10亿 / 10 = 1亿股

    row_b = df[df["symbol"] == "600002"].iloc[0]
    assert row_b["circulating_shares"] == 100_000_000  # 20亿 / 20 = 1亿股


@patch("services.circulating_shares.ak.stock_zh_a_spot_em")
def test_get_circulating_shares(mock_api, clean_file):
    mock_api.return_value = _mock_spot_data()
    update_circulating_shares()

    df = get_circulating_shares()
    assert df is not None
    assert len(df) == 2


def test_get_circulating_shares_no_file(clean_file):
    result = get_circulating_shares()
    assert result is None
