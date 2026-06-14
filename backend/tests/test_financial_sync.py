"""财务 4 表周期同步服务测试(2026-05-27)。

调度任务:周日 02:00 全 A 股拉 EastMoney 4 表,append 去重(REPORT_DATE)。
设计目标:个股失败不阻塞;失败列表落 logs/。
"""

from unittest.mock import MagicMock

import pytest

from services.market_data.updaters import financial_sync


def _mk_record(report_date: str = "2026-03-31"):
    """构造一个最小的财务记录(任何带 REPORT_DATE 的对象即可,append 内部会用 dedup_key)。"""
    rec = MagicMock()
    rec.REPORT_DATE = report_date
    return rec


def test_sync_happy_path(tmp_path):
    """3 只股票全部成功:adapter 4 个 fetch 各返回 1 条,repo 4 个 append 各被调用 3 次。"""
    adapter = MagicMock()
    adapter.fetch_income.return_value = [_mk_record()]
    adapter.fetch_balance.return_value = [_mk_record()]
    adapter.fetch_cashflow.return_value = [_mk_record()]
    adapter.fetch_indicator.return_value = [_mk_record()]

    repo = MagicMock()
    codes = ["600001", "600002", "000001"]

    result = financial_sync.sync_a_share_financial(
        adapter=adapter,
        repo=repo,
        codes=codes,
        throttle=0.0,
        log_dir=tmp_path,
    )

    assert result["success"] == 3
    assert result["failed"] == 0
    assert result["failed_codes"] == []
    assert result["total"] == 3
    assert "elapsed" in result

    assert adapter.fetch_income.call_count == 3
    assert repo.append_income.call_count == 3
    assert repo.append_balance.call_count == 3
    assert repo.append_cashflow.call_count == 3
    assert repo.append_indicator.call_count == 3


def test_sync_partial_failure_does_not_block(tmp_path):
    """1 只 fetch 抛异常,其它 2 只仍成功;失败列表写入 logs。"""
    adapter = MagicMock()

    def _fetch_income(code):
        if code == "600002":
            raise RuntimeError("network timeout")
        return [_mk_record()]

    adapter.fetch_income.side_effect = _fetch_income
    adapter.fetch_balance.return_value = [_mk_record()]
    adapter.fetch_cashflow.return_value = [_mk_record()]
    adapter.fetch_indicator.return_value = [_mk_record()]

    repo = MagicMock()
    codes = ["600001", "600002", "000001"]

    result = financial_sync.sync_a_share_financial(
        adapter=adapter,
        repo=repo,
        codes=codes,
        throttle=0.0,
        log_dir=tmp_path,
    )

    assert result["success"] == 2
    assert result["failed"] == 1
    assert result["failed_codes"] == ["600002"]

    # 失败列表落盘
    failed_files = list(tmp_path.glob("financial_sync_*.failed.txt"))
    assert len(failed_files) == 1
    content = failed_files[0].read_text(encoding="utf-8")
    assert "600002" in content


def test_sync_empty_codes_returns_zero(tmp_path):
    """空 codes 列表早退,不调 adapter,不写文件。"""
    adapter = MagicMock()
    repo = MagicMock()

    result = financial_sync.sync_a_share_financial(
        adapter=adapter,
        repo=repo,
        codes=[],
        throttle=0.0,
        log_dir=tmp_path,
    )

    assert result["success"] == 0
    assert result["failed"] == 0
    assert result["total"] == 0
    adapter.fetch_income.assert_not_called()
    assert list(tmp_path.glob("*.failed.txt")) == []


def test_sync_skips_empty_fetch(tmp_path):
    """fetch 返回空列表(EM 接口对该股没数据)→ 仍计入 success(无异常),repo.append 不被调用。"""
    adapter = MagicMock()
    adapter.fetch_income.return_value = []
    adapter.fetch_balance.return_value = []
    adapter.fetch_cashflow.return_value = []
    adapter.fetch_indicator.return_value = []

    repo = MagicMock()

    result = financial_sync.sync_a_share_financial(
        adapter=adapter,
        repo=repo,
        codes=["600001"],
        throttle=0.0,
        log_dir=tmp_path,
    )

    assert result["success"] == 1
    assert result["failed"] == 0
    repo.append_income.assert_not_called()
    repo.append_balance.assert_not_called()
    repo.append_cashflow.assert_not_called()
    repo.append_indicator.assert_not_called()


def test_sync_no_failed_file_when_all_success(tmp_path):
    """全部成功时不写失败文件。"""
    adapter = MagicMock()
    adapter.fetch_income.return_value = [_mk_record()]
    adapter.fetch_balance.return_value = [_mk_record()]
    adapter.fetch_cashflow.return_value = [_mk_record()]
    adapter.fetch_indicator.return_value = [_mk_record()]
    repo = MagicMock()

    financial_sync.sync_a_share_financial(
        adapter=adapter,
        repo=repo,
        codes=["600001"],
        throttle=0.0,
        log_dir=tmp_path,
    )

    assert list(tmp_path.glob("*.failed.txt")) == []
