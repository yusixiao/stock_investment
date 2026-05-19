import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


SCREENER_CODE = """
from services.backtest.base import ScreenerStrategy

class TestScreener(ScreenerStrategy):
    name = "TestScreener"
    frequency = "daily"

    def screen(self, ctx, symbols):
        return symbols[:2]
"""

BUYER_CODE = """
from services.backtest.base import BuyStrategy

class TestBuyer(BuyStrategy):
    name = "TestBuyer"

    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if sym not in ctx.portfolio.positions:
                ctx.buy(sym, 100)
"""

SELLER_CODE = """
from services.backtest.base import SellStrategy

class TestSeller(SellStrategy):
    name = "TestSeller"

    def on_bar(self, ctx):
        pass
"""


def _make_df(n=20):
    dates = (
        pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    )
    return pd.DataFrame(
        {
            "date": dates,
            "open": [10.0 + i * 0.1 for i in range(n)],
            "high": [10.5 + i * 0.1 for i in range(n)],
            "low": [9.5 + i * 0.1 for i in range(n)],
            "close": [10.0 + i * 0.1 for i in range(n)],
            "volume": [1000000.0] * n,
            "amount": [10000000.0] * n,
        }
    )


@pytest.fixture
def strategy_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "screener.py"), "w") as f:
            f.write(SCREENER_CODE)
        with open(os.path.join(tmpdir, "buyer.py"), "w") as f:
            f.write(BUYER_CODE)
        with open(os.path.join(tmpdir, "seller.py"), "w") as f:
            f.write(SELLER_CODE)
        yield tmpdir


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


def test_group_runner_buy_sell_pipeline(strategy_dir, test_db):
    from services.backtest.group_manager import GroupManager, GroupRunner
    from services.backtest.task_manager import TaskManager

    gm = GroupManager(db_path=test_db)
    tm = TaskManager(db_path=test_db)
    runner = GroupRunner(group_manager=gm, task_manager=tm)

    pipeline = [
        {
            "filepath": os.path.join(strategy_dir, "screener.py"),
            "class_name": "TestScreener",
            "params": {},
        },
        {
            "filepath": os.path.join(strategy_dir, "buyer.py"),
            "class_name": "TestBuyer",
            "params": {},
        },
        {
            "filepath": os.path.join(strategy_dir, "seller.py"),
            "class_name": "TestSeller",
            "params": {},
        },
    ]

    group_id = gm.create_group("TestBuySell", pipeline, join_modes=[])

    mock_raw_dir = Path(tempfile.mkdtemp())
    for sym in ["000001", "000002", "000003"]:
        (mock_raw_dir / f"{sym}.parquet").touch()

    df = _make_df()

    def mock_query_qfq(market, sym, start=None, end=None):
        return df.copy()

    mock_store = MagicMock()
    mock_store.query_qfq_kline.side_effect = mock_query_qfq

    with (
        patch("services.backtest.group_manager.get_store", return_value=mock_store),
        patch("services.backtest.group_manager.RAW_KLINE_DIR", mock_raw_dir),
    ):
        run_id = runner.run_auto(group_id, "2024-01-01", "2024-01-31")

    run = gm.get_run(run_id)
    assert run["status"] == "success"
    assert run["final_result"] is not None
    assert "metrics" in run["final_result"]
    assert "equity_curve" in run["final_result"]


def test_has_buy_sell_detection(strategy_dir, test_db):
    from services.backtest.group_manager import GroupManager, GroupRunner
    from services.backtest.task_manager import TaskManager

    gm = GroupManager(db_path=test_db)
    tm = TaskManager(db_path=test_db)
    runner = GroupRunner(group_manager=gm, task_manager=tm)

    pipeline_with = [
        {
            "filepath": os.path.join(strategy_dir, "screener.py"),
            "class_name": "TestScreener",
            "params": {},
        },
        {
            "filepath": os.path.join(strategy_dir, "buyer.py"),
            "class_name": "TestBuyer",
            "params": {},
        },
    ]
    assert runner._has_buy_sell(pipeline_with) is True

    pipeline_without = [
        {
            "filepath": os.path.join(strategy_dir, "screener.py"),
            "class_name": "TestScreener",
            "params": {},
        },
    ]
    assert runner._has_buy_sell(pipeline_without) is False


def test_build_signal_table(strategy_dir, test_db):
    from services.backtest.group_manager import GroupManager, GroupRunner
    from services.backtest.task_manager import TaskManager

    gm = GroupManager(db_path=test_db)
    tm = TaskManager(db_path=test_db)
    runner = GroupRunner(group_manager=gm, task_manager=tm)

    group_id = gm.create_group(
        "Test", [{"filepath": "x.py", "class_name": "X", "params": {}}]
    )
    run_id = gm.create_run(group_id, "2024-01-01", "2024-01-31", "auto")

    gm.add_exclusion(run_id, "000002")

    final_result = {
        "screened_symbols": [
            {"symbol": "000001", "match_dates": ["2024-01-05", "2024-01-10"]},
            {"symbol": "000002", "match_dates": ["2024-01-05"]},
            {"symbol": "000003", "match_dates": ["2024-01", "2024-01-15"]},
        ]
    }

    table = runner._build_signal_table(final_result, run_id)

    assert "2024-01-05" in table
    assert "000001" in table["2024-01-05"]
    assert "000002" not in table["2024-01-05"]
    assert "2024-01" not in table
    assert "2024-01-15" in table
    assert "000003" in table["2024-01-15"]
