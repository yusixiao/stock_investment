import pytest
import tempfile
import os


@pytest.fixture(autouse=True)
def isolated_task_manager(monkeypatch):
    from services.backtest.task_manager import TaskManager
    import routers.backtest as backtest_router

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name

    try:
        tm = TaskManager(db_path=tmp_path)
        monkeypatch.setattr(backtest_router, "task_manager", tm)
        monkeypatch.setattr("services.backtest.task_manager.task_manager", tm)
        yield tm
    finally:
        os.unlink(tmp_path)
