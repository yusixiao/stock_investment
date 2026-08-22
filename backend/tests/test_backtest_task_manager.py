import sqlite3

import pytest


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
