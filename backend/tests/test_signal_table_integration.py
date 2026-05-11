import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_stock_data():
    dates = [f"2024-01-{d:02d}" for d in range(2, 23)]
    data = {}
    for sym in ["000001", "000002"]:
        base = 10.0 if sym == "000001" else 20.0
        rows = []
        for i, d in enumerate(dates):
            p = base + i * 0.1
            rows.append({"date": d, "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "volume": 1000000, "amount": p * 1000000})
        data[sym] = pd.DataFrame(rows)
    return data


BUYER_CODE = """
from services.backtest.base import BuyStrategy

class TestBuyer(BuyStrategy):
    name = "test"

    def on_bar(self, ctx):
        for sym in ctx.selected_symbols:
            if sym not in ctx.portfolio.positions:
                ctx.buy(sym, 100)
"""

SELLER_CODE = """
from services.backtest.base import SellStrategy

class TestSeller(SellStrategy):
    name = "test"

    def on_bar(self, ctx):
        pass
"""


def test_signal_table_from_source_run():
    from services.backtest.group_manager import GroupManager, GroupRunner
    from services.backtest.task_manager import TaskManager

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        gm = GroupManager(db_path=db_path)
        tm = TaskManager(db_path=db_path)
        runner = GroupRunner(group_manager=gm, task_manager=tm)

        screener_group_id = gm.create_group("screener_group", [
            {"filepath": "x.py", "class_name": "S", "params": {}}
        ])
        screener_run_id = gm.create_run(screener_group_id, "2024-01-02", "2024-01-22", "auto")
        screener_result = {
            "screened_symbols": [
                {"symbol": "000001", "match_dates": ["2024-01-05", "2024-01-10"]},
                {"symbol": "000002", "match_dates": ["2024-01-08"]},
            ]
        }
        gm.update_run_step(screener_run_id, 1, [{"step": 1, "symbols": ["000001", "000002"], "output_count": 2, "input_count": 0}])
        gm.update_run_status(screener_run_id, "success", final_result=screener_result)

        (Path(tmp_dir) / "buyer.py").write_text(BUYER_CODE)
        (Path(tmp_dir) / "seller.py").write_text(SELLER_CODE)

        buy_sell_group_id = gm.create_group("buy_sell_group", [
            {"filepath": str(Path(tmp_dir) / "buyer.py"), "class_name": "TestBuyer", "params": {}},
            {"filepath": str(Path(tmp_dir) / "seller.py"), "class_name": "TestSeller", "params": {}},
        ])

        stock_data = _make_stock_data()
        mock_raw_dir = Path(tmp_dir) / "raw"
        mock_raw_dir.mkdir()
        for sym in stock_data.keys():
            (mock_raw_dir / f"{sym}.parquet").touch()

        def mock_get_qfq(sym, start_date=None, end_date=None):
            return stock_data.get(sym, pd.DataFrame()).copy()

        with patch("services.backtest.group_manager.get_qfq_kline", side_effect=mock_get_qfq), \
             patch("services.backtest.group_manager.RAW_KLINE_DIR", mock_raw_dir):
            run_id = runner.run_auto(buy_sell_group_id, "2024-01-02", "2024-01-22", source_run_id=screener_run_id)

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        result = run["final_result"]
        assert "metrics" in result
        buy_trades = [t for t in result["trades"] if t["direction"] == "buy"]
        buy_dates = set(t["date"] for t in buy_trades)
        assert "2024-01-03" not in buy_dates
