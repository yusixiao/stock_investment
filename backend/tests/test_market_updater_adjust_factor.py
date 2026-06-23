"""复权因子全量更新器测试 — 加固后的 _update_market_adjust_factor(2026-06-23)。

被周六 02:00 scheduler 任务(weekly_adjust_factor_update)调用,属投资关键的
计划数据路径。验证:单 session 复用(login/logout 各一次,而非每只股票一次)、
限流重试、失败隔离不阻塞、空数据跳过。
"""

import types
import time as _real_time
from unittest.mock import MagicMock

import pytest

from services.market_data.updaters import market_updater as mu


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """消除重试退避 + 节流的真实 sleep(保留真实 time.time 供 elapsed 统计)。"""
    fake = types.SimpleNamespace(sleep=lambda *a, **k: None, time=_real_time.time)
    monkeypatch.setattr(mu, "time", fake)


def _patch_deps(monkeypatch, adapter, repo):
    monkeypatch.setattr(mu, "_get_adapter", lambda market: adapter)
    monkeypatch.setattr(mu, "_get_repo", lambda market: repo)


def _rec():
    r = MagicMock()
    r.dividOperateDate = "2026-05-20"
    return r


def test_happy_path_session_reused(monkeypatch):
    """3 只全部成功:写 3 次;login/logout 各 1 次(整批复用单 session)。"""
    adapter = MagicMock()
    adapter.fetch_adjust_factor.return_value = [_rec()]
    repo = MagicMock()
    repo.list_codes.return_value = ["000001.SZ", "600000.SH", "300750.SZ"]
    _patch_deps(monkeypatch, adapter, repo)

    updated = mu._update_market_adjust_factor("A")

    assert updated == 3
    assert adapter.fetch_adjust_factor.call_count == 3
    assert repo.write_adjust_factor.call_count == 3
    assert adapter.login.call_count == 1
    assert adapter.logout.call_count == 1


def test_retry_then_success(monkeypatch):
    """首次 429 → 重试第二次成功,最终计入 updated。"""
    adapter = MagicMock()
    calls = {"n": 0}

    def _fetch(code):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Too Many Requests: 429")
        return [_rec()]

    adapter.fetch_adjust_factor.side_effect = _fetch
    repo = MagicMock()
    repo.list_codes.return_value = ["00700.HK"]
    _patch_deps(monkeypatch, adapter, repo)

    updated = mu._update_market_adjust_factor("HK")

    assert updated == 1
    assert adapter.fetch_adjust_factor.call_count == 2
    assert repo.write_adjust_factor.call_count == 1


def test_failure_isolated_after_retries(monkeypatch):
    """某只重试耗尽仍失败,不阻塞其它;只为成功的写入。"""
    adapter = MagicMock()

    def _fetch(code):
        if code == "BAD":
            raise RuntimeError("permanent error")
        return [_rec()]

    adapter.fetch_adjust_factor.side_effect = _fetch
    repo = MagicMock()
    repo.list_codes.return_value = ["AAA", "BAD", "CCC"]
    _patch_deps(monkeypatch, adapter, repo)

    updated = mu._update_market_adjust_factor("US")

    assert updated == 2
    # AAA(1) + BAD(MAX_RETRIES) + CCC(1)
    assert adapter.fetch_adjust_factor.call_count == 2 + mu.MAX_RETRIES
    assert repo.write_adjust_factor.call_count == 2
    written = {c.args[0] for c in repo.write_adjust_factor.call_args_list}
    assert written == {"AAA", "CCC"}


def test_empty_records_skipped(monkeypatch):
    """fetch 返回空(该股无因子数据)→ 不写、不计 updated。"""
    adapter = MagicMock()
    adapter.fetch_adjust_factor.return_value = []
    repo = MagicMock()
    repo.list_codes.return_value = ["000001.SZ"]
    _patch_deps(monkeypatch, adapter, repo)

    updated = mu._update_market_adjust_factor("A")

    assert updated == 0
    repo.write_adjust_factor.assert_not_called()


def test_no_login_attr_ok(monkeypatch):
    """yfinance 风格 adapter(无 login/logout)不报错。"""
    adapter = MagicMock(spec=["fetch_adjust_factor"])
    adapter.fetch_adjust_factor.return_value = [_rec()]
    repo = MagicMock()
    repo.list_codes.return_value = ["00700.HK"]
    _patch_deps(monkeypatch, adapter, repo)

    updated = mu._update_market_adjust_factor("HK")

    assert updated == 1
    repo.write_adjust_factor.assert_called_once()
