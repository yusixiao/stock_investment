"""K线增量更新的熔断早停测试（P0，2026-07-06）。

背景：baostock 返回 10002007（服务端/会话级网络错误）后，坏 session 上的
后续每只股票都失败，旧逻辑会在坏会话上硬跑完全市场 ~5800 只（每只 3 次重试），
空转 8-13 小时。熔断早停：连续失败达到阈值即中止本市场增量，把损失从数小时
压到数十秒，交由调度层限次延迟重跑（数据源故障多为间歇性）。

验证：
- 持续失败 → 到阈值即 aborted 早停，不再处理剩余股票；
- 成功（含成功但返回空）会重置连续失败计数 → 间歇性故障不误触发（如 06-29
  updated=4107/failed=1155 交错的场景应跑完而非早停）。
"""

import types
import time as _real_time
from unittest.mock import MagicMock

import pytest

from services.market_data.updaters import market_updater as mu


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """消除重试退避 + 节流的真实 sleep（保留真实 time.time 供 elapsed 统计）。"""
    fake = types.SimpleNamespace(sleep=lambda *a, **k: None, time=_real_time.time)
    monkeypatch.setattr(mu, "time", fake)


@pytest.fixture(autouse=True)
def _fixed_end_date(monkeypatch):
    """固定 end_date，避免依赖真实当天时间；确保 start(2010) < end 从而触发 fetch。"""
    monkeypatch.setattr(mu, "_last_closed_trading_date", lambda market: "2026-07-06")


def _patch_deps(monkeypatch, adapter, repo):
    monkeypatch.setattr(mu, "_get_adapter", lambda market: adapter)
    monkeypatch.setattr(mu, "_get_repo", lambda market: repo)


def _make_repo(codes):
    repo = MagicMock()
    repo.list_codes.return_value = codes
    repo.get_latest_date.return_value = None  # 无历史 → 一律走 fetch
    return repo


def test_circuit_breaker_trips_after_consecutive_failures(monkeypatch):
    """全部失败：到阈值即 aborted 早停，剩余股票不再处理，也不写入。"""
    limit = mu.CONSECUTIVE_FAILURE_LIMIT
    codes = [f"C{i}" for i in range(limit + 50)]  # 明显多于阈值

    adapter = MagicMock()
    adapter.fetch_daily_kline.side_effect = RuntimeError(
        "BaoStock error_code=10002007, error_msg=网络接收错误"
    )
    repo = _make_repo(codes)
    _patch_deps(monkeypatch, adapter, repo)

    result = mu._update_market_kline("A")

    assert result.aborted is True
    # 恰好在第 limit 只失败时熔断
    assert result.failed == limit
    # 每只失败会重试 MAX_RETRIES 次，之后即停，剩余股票完全没碰
    assert adapter.fetch_daily_kline.call_count == limit * mu.MAX_RETRIES
    assert repo.get_latest_date.call_count == limit
    repo.append_daily_kline.assert_not_called()


def test_no_trip_when_success_resets_counter(monkeypatch):
    """连续失败被成功打断（永不达阈值）→ 不早停、跑完全部。

    模拟 06-29 那种 updated/failed 交错的间歇性故障。
    """
    limit = mu.CONSECUTIVE_FAILURE_LIMIT
    codes = [f"C{i}" for i in range(3 * limit)]

    def _fetch(code, start, end):
        idx = codes.index(code)
        # 每 limit 个里最后一个成功 → 最大连续失败 = limit-1 < limit
        if (idx + 1) % limit == 0:
            return [MagicMock()]
        raise RuntimeError("BaoStock error_code=10002007")

    adapter = MagicMock()
    adapter.fetch_daily_kline.side_effect = _fetch
    repo = _make_repo(codes)
    _patch_deps(monkeypatch, adapter, repo)

    result = mu._update_market_kline("A")

    assert result.aborted is False
    # 全部 code 被处理（未早停）
    assert repo.get_latest_date.call_count == len(codes)


def test_empty_but_successful_fetch_counts_as_recovery(monkeypatch):
    """fetch 成功但返回空（非交易日/退市）也证明会话健康 → 重置计数。"""
    limit = mu.CONSECUTIVE_FAILURE_LIMIT
    codes = [f"C{i}" for i in range(3 * limit)]

    def _fetch(code, start, end):
        idx = codes.index(code)
        if (idx + 1) % limit == 0:
            return []  # 成功但无数据
        raise RuntimeError("BaoStock error_code=10002007")

    adapter = MagicMock()
    adapter.fetch_daily_kline.side_effect = _fetch
    repo = _make_repo(codes)
    _patch_deps(monkeypatch, adapter, repo)

    result = mu._update_market_kline("A")

    assert result.aborted is False
    assert repo.get_latest_date.call_count == len(codes)


def test_healthy_run_not_aborted(monkeypatch):
    """全部成功：正常完成、不 aborted。"""
    codes = [f"C{i}" for i in range(30)]
    adapter = MagicMock()
    adapter.fetch_daily_kline.return_value = [MagicMock()]
    repo = _make_repo(codes)
    _patch_deps(monkeypatch, adapter, repo)

    result = mu._update_market_kline("A")

    assert result.aborted is False
    assert result.updated == 30
    assert result.failed == 0
    assert repo.append_daily_kline.call_count == 30
