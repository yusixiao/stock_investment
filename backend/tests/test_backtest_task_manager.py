import sqlite3
import inspect

import pytest


def test_task_manager_facade_delegates_to_isolated_collaborators():
    from services.backtest.task_manager import TaskManager

    class Repository:
        def __init__(self):
            self.calls = []
            self.result_row = {
                "status": "success",
                "result": "encoded-result",
                "error": None,
                "summary": "encoded-summary",
                "pipeline_info": "encoded-pipeline",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "source_task_id": None,
                "log_dir": "logs/task-1",
                "trigger_source": "manual",
                "execution_status": "inactive",
                "execution_account_id": None,
            }

        def create_task_row(self, **kwargs):
            self.calls.append(("create_task_row", kwargs))

        def update_task_result(self, *args, **kwargs):
            self.calls.append(("update_task_result", args, kwargs))

        def fail_task(self, *args):
            self.calls.append(("fail_task", args))

        def get_status(self, *args):
            self.calls.append(("get_status", args))
            return "running"

        def get_result_row(self, *args, **kwargs):
            self.calls.append(("get_result_row", args, kwargs))
            return self.result_row

        def list_task_rows(self, **kwargs):
            self.calls.append(("list_task_rows", kwargs))
            return [self.result_row | {"task_id": "task-1", "task_type": "full", "created_at": "now", "is_deleted": 0}]

        def set_execution_account(self, *args, **kwargs):
            self.calls.append(("set_execution_account", args, kwargs))
            return {"task_id": "task-1", "execution_status": "active", "execution_account_id": 7}

        def clear_execution_account(self, *args, **kwargs):
            self.calls.append(("clear_execution_account", args, kwargs))
            return {"task_id": "task-1", "execution_status": "inactive", "execution_account_id": None}

        def delete_task(self, *args):
            self.calls.append(("delete_task", args))

    class Codec:
        def encode(self, value):
            return f"encoded-{value}"

        def build_summary(self, result):
            return "encoded-summary"

        def date_range(self, result):
            return "2026-01-01", "2026-01-02"

        def decode(self, value):
            return {"decoded": value}

        def decode_with_status(self, value):
            return True, {"decoded": value}

    class Progress:
        def __init__(self):
            self.calls = []

        def update(self, *args):
            self.calls.append(("update", args))

        def get(self, *args):
            self.calls.append(("get", args))
            return {"current": 1, "total": 2, "phase": "running"}

        def remove(self, *args):
            self.calls.append(("remove", args))

    repository = Repository()
    codec = Codec()
    progress = Progress()
    manager = TaskManager._from_collaborators(repository, codec, progress)

    task_id = manager.create_task(task_type="full", pipeline_info={"market": "A"})
    manager.complete_task(task_id, {"metrics": {}})
    manager.fail_task(task_id, "failed")
    assert manager.get_status(task_id) == {
        "task_id": task_id,
        "status": "running",
        "progress": {"current": 1, "total": 2, "phase": "running"},
    }
    assert manager.get_result(task_id)["result"] == {"decoded": "encoded-result"}
    assert manager.list_tasks() == [
        {
            "task_id": "task-1",
            "status": "success",
            "task_type": "full",
            "created_at": "now",
            "deleted": False,
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "execution_status": "inactive",
            "execution_account_id": None,
            "trigger_source": "manual",
            "summary": {"decoded": "encoded-summary"},
            "pipeline_info": {"decoded": "encoded-pipeline"},
        }
    ]
    manager.set_execution_account(task_id, 7)
    manager.clear_execution_account(task_id)

    assert [call[0] for call in repository.calls] == [
        "create_task_row",
        "update_task_result",
        "fail_task",
        "get_status",
        "get_result_row",
        "list_task_rows",
        "set_execution_account",
        "clear_execution_account",
    ]


def test_progress_store_isolated_and_cleanup():
    from services.backtest.task_progress import TaskProgressStore

    first = TaskProgressStore()
    second = TaskProgressStore()
    first.update("task-1", 2, 10, "扫描中")

    assert first.get("task-1") == {
        "current": 2,
        "total": 10,
        "phase": "扫描中",
    }
    assert second.get("task-1") is None

    first.remove("task-1")
    assert first.get("task-1") is None


def test_progress_store_get_returns_copy():
    from services.backtest.task_progress import TaskProgressStore

    store = TaskProgressStore()
    store.update("task-1", 2, 10, "扫描中")

    progress = store.get("task-1")
    progress["current"] = 9

    assert store.get("task-1")["current"] == 2


def test_task_manager_progress_facade_preserves_status_shape_and_lifecycle(
    isolated_task_manager,
):
    from services.backtest.task_manager import TaskManager

    assert list(inspect.signature(TaskManager.__init__).parameters) == [
        "self",
        "db_path",
    ]

    task_id = isolated_task_manager.create_task(strategy_class="Example", params={})
    isolated_task_manager.update_progress(task_id, 2, 10, "扫描中")

    assert isolated_task_manager.get_status(task_id) == {
        "task_id": task_id,
        "status": "running",
        "progress": {"current": 2, "total": 10, "phase": "扫描中"},
    }

    isolated_task_manager.complete_task(task_id, {})
    assert isolated_task_manager.get_status(task_id) == {
        "task_id": task_id,
        "status": "success",
    }


def test_task_manager_progress_facade_cleans_up_failed_and_deleted_tasks(
    isolated_task_manager,
):
    failed_id = isolated_task_manager.create_task(strategy_class="Failed", params={})
    isolated_task_manager.update_progress(failed_id, 1, 3, "失败中")
    isolated_task_manager.fail_task(failed_id, "failed")
    assert isolated_task_manager.get_status(failed_id) == {
        "task_id": failed_id,
        "status": "failed",
    }

    deleted_id = isolated_task_manager.create_task(strategy_class="Deleted", params={})
    isolated_task_manager.update_progress(deleted_id, 1, 3, "删除中")
    isolated_task_manager.delete_task(deleted_id)
    assert isolated_task_manager.get_status(deleted_id) == {
        "task_id": deleted_id,
        "status": "running",
    }


class TestExecutionMetadata:
    def test_old_schema_migrates_nullable_trigger_source(self, tmp_path):
        db_path = tmp_path / "old-backtest.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE backtest_tasks (
                task_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'screener', pipeline_info TEXT,
                start_date TEXT, end_date TEXT, summary TEXT, result TEXT,
                error TEXT, created_at TEXT NOT NULL, source_task_id TEXT,
                deleted INTEGER NOT NULL DEFAULT 0, is_deleted INTEGER NOT NULL DEFAULT 0,
                log_dir TEXT, execution_account_id INTEGER,
                execution_status TEXT NOT NULL DEFAULT 'inactive'
            )
            """
        )
        conn.commit()
        conn.close()

        from services.backtest.task_manager import TaskManager

        manager = TaskManager(db_path=str(db_path))
        task_id = manager.create_task(strategy_class="OldStrategy", params={})

        assert manager.get_result(task_id)["trigger_source"] is None

    def test_migration_adds_inactive_execution_columns(self, isolated_task_manager):
        conn = sqlite3.connect(isolated_task_manager._db_path)
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(backtest_tasks)")
        }
        conn.close()

        assert columns["execution_account_id"][3] == 0
        assert columns["execution_status"][4] == "'inactive'"

    def test_setting_and_clearing_execution_account_updates_metadata(
        self, isolated_task_manager
    ):
        task_id = isolated_task_manager.create_task(
            strategy_class="ExampleStrategy", params={}
        )

        assert isolated_task_manager.set_execution_account(task_id, 7) == {
            "task_id": task_id,
            "execution_status": "active",
            "execution_account_id": 7,
        }
        assert isolated_task_manager.get_result(task_id)["status"] == "running"
        assert isolated_task_manager.get_result(task_id)["execution_status"] == "active"
        assert isolated_task_manager.get_result(task_id)["execution_account_id"] == 7

        assert isolated_task_manager.clear_execution_account(task_id) == {
            "task_id": task_id,
            "execution_status": "inactive",
            "execution_account_id": None,
        }

    def test_same_account_or_task_cannot_have_two_active_associations(
        self, isolated_task_manager
    ):
        first = isolated_task_manager.create_task(strategy_class="One", params={})
        second = isolated_task_manager.create_task(strategy_class="Two", params={})
        isolated_task_manager.set_execution_account(first, 7)

        with pytest.raises(ValueError):
            isolated_task_manager.set_execution_account(second, 7)

        isolated_task_manager.set_execution_account(first, 8)
        assert isolated_task_manager.get_result(first)["execution_account_id"] == 8

    def test_list_tasks_orders_active_before_inactive(self, isolated_task_manager):
        inactive_old = isolated_task_manager.create_task(
            strategy_class="Old", params={}
        )
        active = isolated_task_manager.create_task(strategy_class="Active", params={})
        inactive_new = isolated_task_manager.create_task(
            strategy_class="New", params={}
        )
        isolated_task_manager.set_execution_account(active, 7)

        ordered = isolated_task_manager.list_tasks()
        assert [task["task_id"] for task in ordered] == [
            active,
            inactive_new,
            inactive_old,
        ]

    def test_monitor_task_preserves_trigger_metadata(self, isolated_task_manager):
        task_id = isolated_task_manager.create_task(
            task_type="monitor",
            pipeline_info={
                "strategy_class": "ExampleStrategy",
                "trigger_source": "monitor",
                "monitor_id": 7,
            },
            start_date="2026-02-20",
            end_date="2026-08-21",
        )

        task = isolated_task_manager.list_tasks()[0]

        assert task["task_id"] == task_id
        assert task["task_type"] == "monitor"
        assert task["pipeline_info"]["trigger_source"] == "monitor"
        assert task["start_date"] == "2026-02-20"
        assert task["end_date"] == "2026-08-21"

    @pytest.mark.parametrize("descending", [True, False])
    def test_list_tasks_keeps_created_order_inside_each_execution_group(self, isolated_task_manager, descending):
        older = isolated_task_manager.create_task(strategy_class="Older", params={})
        newer = isolated_task_manager.create_task(strategy_class="Newer", params={})
        isolated_task_manager.set_execution_account(older, 9)
        isolated_task_manager.set_execution_account(newer, 10)
        conn = sqlite3.connect(isolated_task_manager._db_path)
        if descending:
            conn.execute("UPDATE backtest_tasks SET created_at = CASE task_id WHEN ? THEN '2026-08-19' ELSE '2026-08-20' END", (older,))
        else:
            conn.execute("UPDATE backtest_tasks SET created_at = CASE task_id WHEN ? THEN '2026-08-20' ELSE '2026-08-19' END", (older,))
        conn.commit()
        conn.close()

        ordered = isolated_task_manager.list_tasks()
        assert [task["task_id"] for task in ordered] == ([newer, older] if descending else [older, newer])


def test_get_result_preserves_null_pipeline_info_and_omits_malformed_json(
    isolated_task_manager,
):
    null_id = isolated_task_manager.create_task(strategy_class="NullPipeline", params={})
    malformed_id = isolated_task_manager.create_task(
        strategy_class="MalformedPipeline", params={}
    )
    conn = sqlite3.connect(isolated_task_manager._db_path)
    conn.execute(
        "UPDATE backtest_tasks SET pipeline_info = CASE task_id WHEN ? THEN 'null' ELSE '{' END",
        (null_id,),
    )
    conn.commit()
    conn.close()

    null_result = isolated_task_manager.get_result(null_id)
    malformed_result = isolated_task_manager.get_result(malformed_id)

    assert "pipeline_info" in null_result
    assert null_result["pipeline_info"] is None
    assert "pipeline_info" not in malformed_result


def test_list_tasks_preserves_null_summary_and_omits_malformed_json(
    isolated_task_manager,
):
    null_id = isolated_task_manager.create_task(strategy_class="NullSummary", params={})
    malformed_id = isolated_task_manager.create_task(
        strategy_class="MalformedSummary", params={}
    )
    conn = sqlite3.connect(isolated_task_manager._db_path)
    conn.execute(
        "UPDATE backtest_tasks SET summary = CASE task_id WHEN ? THEN 'null' ELSE '{' END",
        (null_id,),
    )
    conn.commit()
    conn.close()

    tasks = {task["task_id"]: task for task in isolated_task_manager.list_tasks()}

    assert "summary" in tasks[null_id]
    assert tasks[null_id]["summary"] is None
    assert "summary" not in tasks[malformed_id]


@pytest.mark.parametrize(
    ("result", "expected_summary"),
    [
        (
            {
                "metrics": {
                    "total_return": 0.1,
                    "annual_return": 0.2,
                    "max_drawdown": -0.05,
                    "total_trades": 3,
                }
            },
            {"total_return": 0.1, "annual_return": 0.2, "max_drawdown": -0.05, "total_trades": 3},
        ),
        (
            {
                "hits": ["A"],
                "total_scanned": 2,
                "lookback_used": 30,
                "date_range": {"start": "2026-01-01", "end": "2026-02-01"},
            },
            {"hit_count": 1, "total_scanned": 2, "lookback_used": 30},
        ),
        ({"screened_symbols": ["A", "B"]}, {"screened_count": 2}),
    ],
)
def test_task_manager_preserves_full_scan_and_screener_shapes(
    isolated_task_manager, result, expected_summary
):
    task_id = isolated_task_manager.create_task(strategy_class="Shape", params={})

    isolated_task_manager.complete_task(task_id, result)

    task = isolated_task_manager.get_result(task_id)
    listed = isolated_task_manager.list_tasks()[0]
    assert task["result"] == result
    assert listed["summary"] == expected_summary
