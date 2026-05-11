import tempfile
from pathlib import Path

from services.backtest.strategy_loader import load_strategy_from_file, scan_strategies


def test_load_buy_strategy():
    code = """
from services.backtest.base import BuyStrategy

class MyBuyer(BuyStrategy):
    name = "test_buyer"
    description = "A test buy strategy"
    params = {}

    def on_bar(self, ctx):
        pass
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        classes = load_strategy_from_file(Path(f.name))
    assert len(classes) == 1
    assert classes[0].strategy_type == "buy"
    assert classes[0].name == "test_buyer"


def test_load_sell_strategy():
    code = """
from services.backtest.base import SellStrategy

class MySeller(SellStrategy):
    name = "test_seller"
    description = "A test sell strategy"
    params = {}

    def on_bar(self, ctx):
        pass
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        f.flush()
        classes = load_strategy_from_file(Path(f.name))
    assert len(classes) == 1
    assert classes[0].strategy_type == "sell"
    assert classes[0].name == "test_seller"


def test_scan_returns_buy_sell_types():
    buyer_code = """
from services.backtest.base import BuyStrategy

class MyBuyer(BuyStrategy):
    name = "scan_buyer"
    description = "buyer"
    params = {}

    def on_bar(self, ctx):
        pass
"""
    seller_code = """
from services.backtest.base import SellStrategy

class MySeller(SellStrategy):
    name = "scan_seller"
    description = "seller"
    params = {}

    def on_bar(self, ctx):
        pass
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "buyer.py").write_text(buyer_code)
        (Path(tmpdir) / "seller.py").write_text(seller_code)
        results = scan_strategies(Path(tmpdir))

    types = {r["strategy_type"] for r in results}
    assert "buy" in types
    assert "sell" in types
    names = {r["name"] for r in results}
    assert "scan_buyer" in names
    assert "scan_seller" in names
