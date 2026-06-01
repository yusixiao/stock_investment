"""market_filter:HK_CONNECT 虚拟市场解析 + symbol 过滤。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.backtest.market_filter import (
    HK_CONNECT_MARKET,
    apply_market_filter,
    resolve_data_market,
)


class TestResolveDataMarket:
    def test_a_passthrough(self):
        assert resolve_data_market("A") == "A"

    def test_hk_passthrough(self):
        assert resolve_data_market("HK") == "HK"

    def test_us_passthrough(self):
        assert resolve_data_market("US") == "US"

    def test_hk_connect_maps_to_hk(self):
        # 虚拟市场必须解析回 HK 物理市场,否则 data_cache.get_market 会拒收
        assert resolve_data_market(HK_CONNECT_MARKET) == "HK"
        assert resolve_data_market("hk_connect") == "HK"

    def test_lowercase_normalized(self):
        assert resolve_data_market("a") == "A"

    def test_none_defaults_to_a(self):
        assert resolve_data_market(None) == "A"  # type: ignore[arg-type]


class TestApplyMarketFilter:
    def test_a_market_passthrough_with_symbols(self):
        symbols = ["000001.SZ", "600519.SH"]
        assert apply_market_filter("A", symbols) is symbols

    def test_a_market_passthrough_none(self):
        assert apply_market_filter("A", None) is None

    def test_hk_market_passthrough(self):
        symbols = ["00700.HK"]
        assert apply_market_filter("HK", symbols) is symbols

    def test_us_market_passthrough(self):
        assert apply_market_filter("US", None) is None

    @patch("services.hk_connect_updater.get_latest_hk_connect_codes")
    def test_hk_connect_none_returns_full_pool(self, mock_codes):
        mock_codes.return_value = ["00700", "09988", "03690"]
        result = apply_market_filter(HK_CONNECT_MARKET, None)
        assert result == ["00700.HK", "03690.HK", "09988.HK"]  # sorted

    @patch("services.hk_connect_updater.get_latest_hk_connect_codes")
    def test_hk_connect_intersection_preserves_order(self, mock_codes):
        mock_codes.return_value = ["00700", "09988", "03690"]
        # 用户传混合列表,只保留港股通成员且按用户原始顺序
        requested = ["09988.HK", "00001.HK", "00700.HK", "08888.HK"]
        result = apply_market_filter(HK_CONNECT_MARKET, requested)
        assert result == ["09988.HK", "00700.HK"]

    @patch("services.hk_connect_updater.get_latest_hk_connect_codes")
    def test_hk_connect_empty_intersection(self, mock_codes):
        mock_codes.return_value = ["00700"]
        requested = ["00001.HK", "08888.HK"]
        result = apply_market_filter(HK_CONNECT_MARKET, requested)
        assert result == []

    @patch("services.hk_connect_updater.get_latest_hk_connect_codes")
    def test_hk_connect_parquet_missing_returns_empty(self, mock_codes):
        # parquet 缺失时 updater 返回空列表 → HK_CONNECT 退化为空池
        mock_codes.return_value = []
        result = apply_market_filter(HK_CONNECT_MARKET, None)
        assert result == []

    @patch("services.hk_connect_updater.get_latest_hk_connect_codes")
    def test_hk_connect_lowercase_normalized(self, mock_codes):
        mock_codes.return_value = ["00700"]
        result = apply_market_filter("hk_connect", None)
        assert result == ["00700.HK"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
