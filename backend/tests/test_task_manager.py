import pytest
from services.backtest.task_manager import TaskManager


@pytest.fixture
def tm(tmp_path):
    return TaskManager(db_path=str(tmp_path / "test.db"))


def test_delete_task_marks_deleted(tm):
    task_id = tm.create_task(task_type="screener")
    tm.delete_task(task_id)
    tasks = tm.list_tasks(show_deleted=True)
    match = next(t for t in tasks if t["task_id"] == task_id)
    assert match["deleted"] is True


def test_list_tasks_hides_deleted_by_default(tm):
    task_id = tm.create_task(task_type="screener")
    tm.delete_task(task_id)
    tasks = tm.list_tasks(show_deleted=False)
    assert all(t["task_id"] != task_id for t in tasks)


def test_list_tasks_shows_deleted_when_requested(tm):
    task_id = tm.create_task(task_type="screener")
    tm.delete_task(task_id)
    tasks = tm.list_tasks(show_deleted=True)
    assert any(t["task_id"] == task_id for t in tasks)


def test_delete_nonexistent_task_does_not_raise(tm):
    tm.delete_task("nonexistent")
