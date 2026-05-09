import json
import pytest
from services.backtest.group_manager import GroupManager


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
