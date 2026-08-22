"""熔断早停市场的限次延迟重跑测试（P0，2026-07-06）。

_market_update_job 拿到 update_all_markets 结果后,对 aborted 的市场安排延迟重跑;
_market_retry_job 逐市场重试,仍失败且未达上限则再排下一次,否则告警放弃;任一市场
重试成功需重建衍生缓存(circulating_shares + data_cache)。
"""

from unittest.mock import MagicMock

import pytest

import scheduler as sched
from services.market_data.updaters import market_updater as mu
from services.market_data.refresh_runner import RefreshRunner


@pytest.fixture
def mock_add_job(monkeypatch):
    m = MagicMock()
    monkeypatch.setattr(sched.scheduler, "add_job", m)
    return m


@pytest.fixture(autouse=True)
def mock_refresh_runner(monkeypatch, tmp_path):
    """保留 runner 状态测试，但禁止真实 cache 重建。"""
    def factory(**kwargs):
        kwargs["refresh_before_cache"] = lambda markets: None
        return RefreshRunner(
            tmp_path / "refresh.db",
            refresh_view=lambda market: {"status": "success"},
            refresh_cache=lambda market, refresh_id=None: {
                "status": "ready", "stale": False
            },
            **kwargs,
        )

    monkeypatch.setattr(sched, "_make_refresh_runner", factory)


def _results(*aborted_markets):
    out = []
    for m in ("A", "HK", "US"):
        out.append(mu.MarketUpdateResult(market=m, aborted=(m in aborted_markets)))
    return out


def test_job_schedules_retry_when_market_aborted(monkeypatch, mock_add_job):
    monkeypatch.setattr(mu, "update_all_markets", lambda parallel=True: _results("A"))

    sched._market_update_job()

    assert mock_add_job.call_count == 1
    call = mock_add_job.call_args
    assert call.args[1] == "date"  # 一次性延迟触发
    assert call.kwargs["args"] == [["A"], 1]  # 只重试 aborted 的 A,attempt=1
    assert call.kwargs["run_date"] is not None


def test_job_no_retry_when_none_aborted(monkeypatch, mock_add_job):
    monkeypatch.setattr(mu, "update_all_markets", lambda parallel=True: _results())

    sched._market_update_job()

    assert mock_add_job.call_count == 0


def test_retry_reschedules_when_still_aborted_below_max(monkeypatch, mock_add_job):
    monkeypatch.setattr(
        mu, "update_single_market",
        lambda market: mu.MarketUpdateResult(market=market, aborted=True),
    )

    sched._market_retry_job(["A"], attempt=1)

    assert mock_add_job.call_count == 1
    assert mock_add_job.call_args.kwargs["args"] == [["A"], 2]  # attempt+1


def test_retry_gives_up_at_max(monkeypatch, mock_add_job):
    monkeypatch.setattr(
        mu, "update_single_market",
        lambda market: mu.MarketUpdateResult(market=market, aborted=True),
    )

    sched._market_retry_job(["A"], attempt=sched.MARKET_RETRY_MAX_ATTEMPTS)

    assert mock_add_job.call_count == 0  # 达上限,放弃,不再排


def test_retry_success_refreshes_and_stops(monkeypatch, mock_add_job):
    monkeypatch.setattr(
        mu, "update_single_market",
        lambda market: mu.MarketUpdateResult(market=market, aborted=False),
    )

    sched._market_retry_job(["A"], attempt=1)

    assert mock_add_job.call_count == 0  # 成功,不再重排


def test_retry_exception_counts_as_aborted(monkeypatch, mock_add_job):
    def _raise(market):
        raise RuntimeError("boom")

    monkeypatch.setattr(mu, "update_single_market", _raise)

    sched._market_retry_job(["A"], attempt=1)

    assert mock_add_job.call_count == 1  # 异常视为仍失败 → 继续重排


def test_main_and_retry_use_same_refresh_contract(monkeypatch, tmp_path):
    calls = []

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def start(self, source, markets=None):
            return MagicMock(refresh_id="refresh-id")

        def run(self, refresh_id, markets):
            return None

    monkeypatch.setattr(sched, "_make_refresh_runner", FakeRunner)
    monkeypatch.setattr(mu, "update_all_markets", lambda parallel=True: _results())
    monkeypatch.setattr(mu, "update_single_market", lambda market: mu.MarketUpdateResult(market=market))

    sched._market_update_job()
    sched._market_retry_job(["A"], attempt=1)

    assert calls[0]["refresh_before_cache"] is sched._refresh_circulating_shares
    assert calls[1]["refresh_before_cache"] is sched._refresh_circulating_shares
    assert calls[0]["on_complete"] is calls[1]["on_complete"]


@pytest.mark.parametrize("source", ["scheduler_retry_bad", "scheduler_retry_not-a-number"])
def test_malformed_retry_source_still_notifies_ready_markets(
    monkeypatch, mock_add_job, source
):
    strategy = MagicMock()
    stock = MagicMock()
    monkeypatch.setattr("services.monitoring.strategy_monitor.run_due_strategy_monitors", strategy)
    monkeypatch.setattr("services.monitoring.stock_price_monitor.evaluate_stock_price_monitors", stock)

    record = MagicMock(source=source, status="partial", market_states={
        "A": {
            "update": {"status": "failed", "detail": {"aborted": True}},
            "view": {"status": "failed"},
            "cache": {"status": "failed"},
            "result": {"status": "stale"},
        },
        "HK": {
            "update": {"status": "success"},
            "view": {"status": "success"},
            "cache": {"status": "success"},
            "result": {"status": "ready"},
        },
    })

    sched._on_market_refresh_complete(record)

    mock_add_job.assert_not_called()
    assert [call.kwargs["markets"] for call in strategy.call_args_list] == [{"HK"}]
    assert [call.kwargs["markets"] for call in stock.call_args_list] == [{"HK"}]
