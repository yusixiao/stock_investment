import sqlite3

import pytest


def _create_task(repository, pipeline_info):
    repository.create_task_row(
        task_id="task-1",
        task_type="screener",
        pipeline_info=pipeline_info,
        start_date=None,
        end_date=None,
        source_task_id=None,
        created_at="2026-08-22T10:00:00",
        log_dir="logs/task-1",
        trigger_source=None,
    )


@pytest.mark.parametrize("pipeline_info", [None, "", "{", "[]", '"text"', "1"])
def test_repository_metadata_update_recovers_dirty_or_non_dict_pipeline_info(
    tmp_path, pipeline_info
):
    from services.backtest.task_repository import TaskRepository

    repository = TaskRepository(str(tmp_path / "tasks.db"))
    _create_task(repository, pipeline_info)

    repository.update_task_metadata("task-1", {"strategy_name": "Updated"})

    row = repository.get_result_row("task-1")
    assert row["pipeline_info"] == '{"strategy_name": "Updated"}'


def test_repository_metadata_update_is_atomic_on_one_immediate_transaction(tmp_path):
    from services.backtest.task_repository import TaskRepository

    repository = TaskRepository(str(tmp_path / "tasks.db"))
    _create_task(repository, '{"existing":"keep"}')
    real_connection = repository._get_conn()

    class RecordingConnection:
        def __init__(self, connection):
            self.connection = connection
            self.operations = []

        def execute(self, sql, parameters=()):
            self.operations.append(("execute", sql))
            if sql.startswith("UPDATE backtest_tasks"):
                raise RuntimeError("write failed")
            return self.connection.execute(sql, parameters)

        def commit(self):
            self.operations.append(("commit",))
            return self.connection.commit()

        def rollback(self):
            self.operations.append(("rollback",))
            return self.connection.rollback()

        def close(self):
            self.operations.append(("close",))
            return self.connection.close()

    recording = RecordingConnection(real_connection)
    repository._get_conn = lambda: recording

    with pytest.raises(RuntimeError, match="write failed"):
        repository.update_task_metadata("task-1", {"strategy_name": "Updated"})

    assert [operation[0] for operation in recording.operations] == [
        "execute",
        "execute",
        "execute",
        "rollback",
        "close",
    ]
    assert recording.operations[0][1] == "BEGIN IMMEDIATE"


def test_repository_persists_task_rows_and_updates_result(tmp_path):
    from services.backtest.task_repository import TaskRepository

    repository = TaskRepository(str(tmp_path / "tasks.db"))
    repository.create_task_row(
        task_id="task-1",
        task_type="screener",
        pipeline_info='{"strategy_class":"Example"}',
        start_date="2026-01-01",
        end_date="2026-02-01",
        source_task_id=None,
        created_at="2026-08-22T10:00:00",
        log_dir="logs/task-1",
        trigger_source=None,
    )

    assert repository.get_status("task-1") == "running"

    repository.update_task_result(
        "task-1",
        result='{"metrics":{"total_return":0.1}',
        summary='{"total_return":0.1}',
        date_start="2026-01-01",
        date_end="2026-02-01",
    )

    row = repository.get_result_row("task-1")
    assert row["status"] == "success"
    assert row["result"] == '{"metrics":{"total_return":0.1}'
    assert row["summary"] == '{"total_return":0.1}'


def test_repository_marks_failure_and_soft_deletes(tmp_path):
    from services.backtest.task_repository import TaskRepository

    repository = TaskRepository(str(tmp_path / "tasks.db"))
    repository.create_task_row(
        task_id="task-1",
        task_type="screener",
        pipeline_info='{"strategy_class":"Example"}',
        start_date=None,
        end_date=None,
        source_task_id=None,
        created_at="2026-08-22T10:00:00",
        log_dir="logs/task-1",
        trigger_source=None,
    )

    repository.fail_task("task-1", "worker failed")
    assert repository.get_result_row("task-1")["error"] == "worker failed"
    assert repository.get_status("task-1") == "failed"

    repository.delete_task("task-1")
    row = repository.get_result_row("task-1")
    assert row["is_deleted"] == 1
    assert row["deleted"] == 1


def test_repository_recovers_running_tasks_at_startup(tmp_path):
    from services.backtest.task_repository import TaskRepository

    db_path = str(tmp_path / "tasks.db")
    first = TaskRepository(db_path)
    first.create_task_row(
        task_id="task-1",
        task_type="screener",
        pipeline_info='{"strategy_class":"Example"}',
        start_date=None,
        end_date=None,
        source_task_id=None,
        created_at="2026-08-22T10:00:00",
        log_dir="logs/task-1",
        trigger_source=None,
    )

    second = TaskRepository(db_path)
    row = second.get_result_row("task-1")
    assert row["status"] == "failed"
    assert row["error"] == "服务重启，任务中断"


def test_repository_lists_non_deleted_rows_in_active_then_created_order(tmp_path):
    from services.backtest.task_repository import TaskRepository

    repository = TaskRepository(str(tmp_path / "tasks.db"))
    for task_id, created_at in (("old", "2026-08-20"), ("new", "2026-08-21"), ("active", "2026-08-19")):
        repository.create_task_row(
            task_id=task_id,
            task_type="screener",
            pipeline_info='{"strategy_class":"Example"}',
            start_date=None,
            end_date=None,
            source_task_id=None,
            created_at=created_at,
            log_dir=f"logs/{task_id}",
            trigger_source=None,
        )
    repository.set_execution_account("active", 7)
    repository.delete_task("old")

    rows = repository.list_task_rows()
    assert [row["task_id"] for row in rows] == ["active", "new"]
    assert all(isinstance(row, sqlite3.Row) for row in rows)


def test_repository_account_binding_is_transactional_and_unique(tmp_path):
    from services.backtest.task_repository import TaskRepository

    repository = TaskRepository(str(tmp_path / "tasks.db"))
    for task_id in ("first", "second"):
        repository.create_task_row(
            task_id=task_id,
            task_type="screener",
            pipeline_info='{"strategy_class":"Example"}',
            start_date=None,
            end_date=None,
            source_task_id=None,
            created_at="2026-08-22T10:00:00",
            log_dir=f"logs/{task_id}",
            trigger_source=None,
        )

    assert repository.set_execution_account("first", 7)["execution_account_id"] == 7
    with pytest.raises(ValueError):
        repository.set_execution_account("second", 7)
    assert repository.get_result_row("second")["execution_status"] == "inactive"
    assert repository.clear_execution_account("first")["execution_account_id"] is None
