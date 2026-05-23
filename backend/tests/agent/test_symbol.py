"""问股期 1 — Task 3:股票码 normalize + extract 测试。"""

from unittest.mock import MagicMock

from services.agent.symbol import StockRef, extract, normalize


class TestNormalize:
    def test_a_share_sh(self):
        assert normalize("600519") == "600519.SH"

    def test_a_share_sz(self):
        assert normalize("002594") == "002594.SZ"

    def test_a_share_creation_board(self):
        assert normalize("300750") == "300750.SZ"

    def test_a_share_star_board(self):
        assert normalize("688981") == "688981.SH"

    def test_already_suffixed_a(self):
        assert normalize("600519.SH") == "600519.SH"

    def test_already_suffixed_a_lowercase(self):
        assert normalize("600519.sh") == "600519.SH"

    def test_hk(self):
        assert normalize("00700") == "00700.HK"

    def test_hk_short(self):
        assert normalize("700.HK") == "00700.HK"

    def test_hk_lowercase_suffix(self):
        assert normalize("9988.hk") == "09988.HK"

    def test_us_no_suffix(self):
        assert normalize("AAPL") == "AAPL"

    def test_us_lowercase(self):
        assert normalize("aapl") == "AAPL"

    def test_us_with_us_suffix(self):
        assert normalize("AAPL.US") == "AAPL"


class TestExtract:
    def test_from_context(self):
        ctx = {"stock_code": "002594", "stock_name": "比亚迪"}
        si = MagicMock()
        si.get_name.return_value = "比亚迪"
        ref = extract("帮我看看", ctx, stock_index=si)
        assert ref == StockRef(code="002594.SZ", name="比亚迪", market="A")

    def test_from_message_with_code(self):
        si = MagicMock()
        si.get_name.return_value = "贵州茅台"
        ref = extract("分析 600519", None, stock_index=si)
        assert ref.code == "600519.SH"
        assert ref.market == "A"

    def test_no_match_returns_none(self):
        si = MagicMock()
        si.get_name.return_value = None
        assert extract("你好", None, stock_index=si) is None

    def test_us_ticker(self):
        si = MagicMock()
        si.get_name.return_value = "Apple Inc"
        ref = extract("AAPL 怎么样", None, stock_index=si)
        assert ref.code == "AAPL"
        assert ref.market == "US"

    def test_hk_ticker(self):
        si = MagicMock()
        si.get_name.return_value = "腾讯控股"
        ref = extract("00700 港股", None, stock_index=si)
        assert ref.code == "00700.HK"
        assert ref.market == "HK"

    def test_context_empty_falls_through(self):
        si = MagicMock()
        si.get_name.return_value = "宁德时代"
        ref = extract("300750", {}, stock_index=si)
        assert ref.code == "300750.SZ"
