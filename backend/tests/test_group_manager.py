import json
import pytest
from unittest.mock import patch, MagicMock
from services.backtest.group_manager import GroupManager, GroupRunner


@pytest.fixture
def gm(tmp_path):
    db_path = str(tmp_path / "test.db")
    return GroupManager(db_path=db_path)


class TestGroupCRUD:
    def test_create_group(self, gm):
        pipeline = [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {"fast": 5, "slow": 20}}]
        group_id = gm.create_group("测试策略组", pipeline, ["correlated"])
        assert group_id
        group = gm.get_group(group_id)
        assert group["name"] == "测试策略组"
        assert group["pipeline"] == pipeline
        assert group["join_modes"] == ["correlated"]

    def test_list_groups(self, gm):
        gm.create_group("组A", [{"filepath": "a.py", "class_name": "A"}], [])
        gm.create_group("组B", [{"filepath": "b.py", "class_name": "B"}], [])
        groups = gm.list_groups()
        assert len(groups) == 2

    def test_update_group(self, gm):
        gid = gm.create_group("旧名", [{"filepath": "a.py", "class_name": "A"}], [])
        gm.update_group(gid, name="新名")
        group = gm.get_group(gid)
        assert group["name"] == "新名"

    def test_delete_group(self, gm):
        gid = gm.create_group("待删", [{"filepath": "a.py", "class_name": "A"}], [])
        gm.delete_group(gid)
        assert gm.get_group(gid) is None
        assert len(gm.list_groups()) == 0

    def test_delete_group_cascades_runs(self, gm):
        gid = gm.create_group("有运行", [{"filepath": "a.py", "class_name": "A"}], [])
        run_id = gm.create_run(gid, "2024-01-01", "2024-12-31", "auto")
        gm.delete_group(gid)
        assert gm.get_run(run_id) is None


@pytest.fixture
def runner(tmp_path):
    db_path = str(tmp_path / "test.db")
    from services.backtest.task_manager import TaskManager
    tm = TaskManager(db_path=db_path)
    gm = GroupManager(db_path=db_path)
    return GroupRunner(gm, tm)


class TestGroupRunner:
    def test_auto_run_single_screener(self, runner):
        gm = runner._group_manager
        pipeline = [{"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}}]
        gid = gm.create_group("单步选股", pipeline, [])

        mock_result = {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}]}
        with patch("services.backtest.group_manager._execute_step") as mock_exec:
            mock_exec.return_value = ("task123", mock_result)
            run_id = runner.run_auto(gid, "2024-01-01", "2024-12-31")

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        assert len(run["steps_result"]) == 1

    def test_auto_run_chained_screeners(self, runner):
        gm = runner._group_manager
        pipeline = [
            {"filepath": "strategies/examples/ma_cross_screener.py", "class_name": "MaCrossScreener", "frequency": "daily", "params": {}},
            {"filepath": "strategies/examples/macd_screener.py", "class_name": "MacdScreener", "frequency": "daily", "params": {}},
        ]
        gid = gm.create_group("两步选股", pipeline, ["correlated"])

        results = [
            ("t1", {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}, {"symbol": "000002", "match_dates": ["2024-01-15"]}]}),
            ("t2", {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}]}),
        ]
        call_count = [0]

        def side_effect(*args, **kwargs):
            r = results[call_count[0]]
            call_count[0] += 1
            return r

        with patch("services.backtest.group_manager._execute_step", side_effect=side_effect):
            run_id = runner.run_auto(gid, "2024-01-01", "2024-12-31")

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        steps = run["steps_result"]
        assert len(steps) == 2
        assert steps[0]["output_count"] == 2
        assert steps[1]["input_count"] == 2

    def test_stepwise_run(self, runner):
        gm = runner._group_manager
        pipeline = [
            {"filepath": "a.py", "class_name": "A", "frequency": "daily", "params": {}},
            {"filepath": "b.py", "class_name": "B", "frequency": "daily", "params": {}},
        ]
        gid = gm.create_group("逐步", pipeline, ["correlated"])

        mock_result = {"screened_symbols": [{"symbol": "000001", "match_dates": ["2024-01-15"]}]}
        with patch("services.backtest.group_manager._execute_step") as mock_exec:
            mock_exec.return_value = ("t1", mock_result)
            run_id = runner.run_stepwise_start(gid, "2024-01-01", "2024-12-31")

        run = gm.get_run(run_id)
        assert run["status"] == "step_1_done"
        assert run["current_step"] == 1

        with patch("services.backtest.group_manager._execute_step") as mock_exec:
            mock_exec.return_value = ("t2", mock_result)
            runner.run_stepwise_next(run_id)

        run = gm.get_run(run_id)
        assert run["status"] == "success"
        assert run["current_step"] == 2


class TestMigration:
    def test_migrate_chain(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        from services.backtest.task_manager import TaskManager
        tm = TaskManager(db_path=db_path)
        gm = GroupManager(db_path=db_path)

        t1 = tm.create_task(task_type="screener", pipeline_info={"strategies": [{"class_name": "MaCross", "name": "均线交叉"}]}, start_date="2024-01-01", end_date="2024-12-31")
        tm.complete_task(t1, {"screened_symbols": ["000001", "000002"]})
        t2 = tm.create_task(task_type="screener", pipeline_info={"strategies": [{"class_name": "MacdFilter", "name": "MACD过滤"}]}, start_date="2024-01-01", end_date="2024-12-31", source_task_id=t1)
        tm.complete_task(t2, {"screened_symbols": ["000001"]})

        count = gm.migrate_from_tasks(tm)
        assert count == 1
        groups = gm.list_groups()
        assert len(groups) == 1
        assert len(groups[0]["pipeline"]) == 2

    def test_migrate_no_chains(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        from services.backtest.task_manager import TaskManager
        tm = TaskManager(db_path=db_path)
        gm = GroupManager(db_path=db_path)

        t1 = tm.create_task(task_type="screener", pipeline_info={"strategies": [{"class_name": "A"}]}, start_date="2024-01-01", end_date="2024-12-31")
        tm.complete_task(t1, {"screened_symbols": ["000001"]})

        count = gm.migrate_from_tasks(tm)
        assert count == 0
