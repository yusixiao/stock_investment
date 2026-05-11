import tempfile
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.backtest.group_manager import GroupManager


def _make_manager():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return GroupManager(db_path=tmp.name), tmp.name


def test_create_run_with_initial_capital():
    gm, db_path = _make_manager()
    try:
        group_id = gm.create_group("test", [{"filepath": "a.py", "class_name": "A"}])
        run_id = gm.create_run(group_id, "2024-01-01", "2024-12-31", "auto", initial_capital=500_000)
        run = gm.get_run(run_id)
        assert run["initial_capital"] == 500_000
    finally:
        os.unlink(db_path)


def test_create_run_default_capital():
    gm, db_path = _make_manager()
    try:
        group_id = gm.create_group("test", [{"filepath": "a.py", "class_name": "A"}])
        run_id = gm.create_run(group_id, "2024-01-01", "2024-12-31", "auto")
        run = gm.get_run(run_id)
        assert run["initial_capital"] == 1_000_000
    finally:
        os.unlink(db_path)
