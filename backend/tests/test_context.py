"""新 Context 单测(Phase 3.1)。"""

import json
from unittest.mock import MagicMock

import pytest

from services.backtest.context import Context
from services.backtest.decision_log import DecisionLogSink


@pytest.fixture
def ctx(tmp_path):
    strategy = MagicMock(frequency="monthly")
    broker = MagicMock()
    broker.portfolio.available_cash = 100_000
    market_data = MagicMock()
    market_data.dates = ["2024-01-31", "2024-02-29", "2024-03-29"]
    sink = DecisionLogSink(tmp_path, enabled=True)
    return Context(
        strategy=strategy,
        idx=2,
        broker=broker,
        market_data=market_data,
        log_sink=sink,
    )


def test_current_date_and_idx(ctx):
    assert ctx.current_idx == 2
    assert ctx.current_date == "2024-03-29"


def test_strategy_attached(ctx):
    assert ctx.strategy.frequency == "monthly"


def test_set_pool_injects_target_and_new(ctx):
    pool = {"A", "B", "C"}
    new = ["B", "C"]
    removed = []
    ctx.set_pool(pool, new, remove_callback=removed.append)
    assert ctx.target_symbols == {"A", "B", "C"}
    assert ctx.new_symbols == ["B", "C"]
    ctx.remove_target("B")
    assert removed == ["B"]


def test_remove_target_without_callback_is_noop(ctx):
    # 默认未注入 callback,调用应安全无副作用
    ctx.remove_target("000001")


def test_default_pool_empty(ctx):
    assert ctx.target_symbols == set()
    assert ctx.new_symbols == []


def test_log_pass_injects_idx_ts_freq(ctx, tmp_path):
    ctx.log_pass("000001", "test.stage", value=42)
    ctx.log_sink.flush()
    rec = json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["idx"] == 2
    assert rec["ts"] == "2024-03-29"
    assert rec["freq"] == "monthly"
    assert rec["value"] == 42
    assert rec["decision"] == "pass"
    assert rec["stage"] == "test.stage"
    assert rec["symbol"] == "000001"


def test_log_reject_injects_common_kwargs(ctx, tmp_path):
    ctx.log_reject("000002", "filter.pe", reason="pe>50", pe=60.0)
    ctx.log_sink.flush()
    rec = json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["decision"] == "reject"
    assert rec["reason"] == "pe>50"
    assert rec["idx"] == 2
    assert rec["ts"] == "2024-03-29"
    assert rec["freq"] == "monthly"
    assert rec["pe"] == 60.0


def test_log_flow_writes_counts(ctx, tmp_path):
    ctx.log_flow("screen.in", input=100, passed=30)
    ctx.log_sink.flush()
    rec = json.loads((tmp_path / "flow.jsonl").read_text().strip())
    assert rec["idx"] == 2
    assert rec["ts"] == "2024-03-29"
    assert rec["stage"] == "screen.in"
    assert rec["counts"] == {"input": 100, "passed": 30}


def test_log_exec_writes_action(ctx, tmp_path):
    ctx.log_exec("buy", "000001", shares=100, price=10.5, note="rebalance")
    ctx.log_sink.flush()
    rec = json.loads((tmp_path / "exec.jsonl").read_text().strip())
    assert rec["action"] == "buy"
    assert rec["symbol"] == "000001"
    assert rec["shares"] == 100
    assert rec["price"] == 10.5
    assert rec["note"] == "rebalance"
    assert rec["idx"] == 2
    assert rec["ts"] == "2024-03-29"


def test_get_price_delegates_to_market_data(ctx):
    ctx._market_data.get_price.return_value = {"close": 35.2}
    assert ctx.get_price("000001")["close"] == 35.2
    ctx._market_data.get_price.assert_called_once_with("000001", period="daily", idx=2)


def test_get_history_delegates_with_period(ctx):
    ctx._market_data.get_history.return_value = [1, 2, 3]
    assert ctx.get_history("000001", n=20, period="weekly") == [1, 2, 3]
    ctx._market_data.get_history.assert_called_once_with(
        "000001", n=20, period="weekly", idx=2
    )


def test_get_valuation_delegates_with_date(ctx):
    ctx._market_data.get_valuation.return_value = {"pe": 12.0}
    assert ctx.get_valuation("000001") == {"pe": 12.0}
    ctx._market_data.get_valuation.assert_called_once_with("000001", date="2024-03-29")


def test_get_dividend_delegates_with_date(ctx):
    ctx._market_data.get_dividend.return_value = []
    ctx.get_dividend("000001")
    ctx._market_data.get_dividend.assert_called_once_with("000001", date="2024-03-29")


def test_get_financial_delegates_with_date(ctx):
    ctx._market_data.get_financial.return_value = {}
    ctx.get_financial("000001")
    ctx._market_data.get_financial.assert_called_once_with("000001", date="2024-03-29")


def test_indicator_passes_kwargs(ctx):
    ctx._market_data.indicator.return_value = 1.5
    assert ctx.indicator("ma", "000001", n=20) == 1.5
    ctx._market_data.indicator.assert_called_once_with("ma", "000001", idx=2, n=20)


def test_available_cash_property(ctx):
    assert ctx.available_cash == 100_000


def test_get_position_delegates(ctx):
    ctx._broker.portfolio.get_position.return_value = "POS"
    assert ctx.get_position("000001") == "POS"
    ctx._broker.portfolio.get_position.assert_called_once_with("000001")


def test_get_positions_delegates(ctx):
    ctx._broker.portfolio.positions = {"000001": "POS"}
    assert ctx.get_positions() == {"000001": "POS"}


def test_order_shares_delegates_to_broker(ctx):
    ctx.order_shares("000001", 100)
    ctx._broker.submit_order.assert_called_once()
    kwargs = ctx._broker.submit_order.call_args.kwargs
    assert kwargs["symbol"] == "000001"
    assert kwargs["shares"] == 100
    assert kwargs["direction"] == "buy"


def test_order_shares_negative_is_sell(ctx):
    ctx.order_shares("000001", -200)
    kwargs = ctx._broker.submit_order.call_args.kwargs
    assert kwargs["shares"] == 200
    assert kwargs["direction"] == "sell"


def test_order_shares_zero_no_op(ctx):
    assert ctx.order_shares("000001", 0) is None
    ctx._broker.submit_order.assert_not_called()


def test_order_value_rounds_to_lot(ctx):
    ctx._market_data.get_price.return_value = {"close": 10.0}
    # 1050 / 10 = 105 股 → 取整百 → 100 股
    ctx.order_value("000001", 1050)
    kwargs = ctx._broker.submit_order.call_args.kwargs
    assert kwargs["shares"] == 100


def test_order_value_below_lot_returns_none(ctx):
    ctx._market_data.get_price.return_value = {"close": 100.0}
    # 50 / 100 = 0 股 → < 100 不下单
    result = ctx.order_value("000001", 50)
    assert result is None
    ctx._broker.submit_order.assert_not_called()


def test_order_value_no_price_returns_none(ctx):
    ctx._market_data.get_price.return_value = None
    assert ctx.order_value("000001", 1000) is None
    ctx._broker.submit_order.assert_not_called()


def test_order_target_percent_uses_equity(ctx):
    ctx._broker.portfolio.equity.return_value = 1_000_000
    ctx._market_data.get_price.return_value = {"close": 10.0}
    # 10% × 100w = 10w → 10000 股 → 取整百仍是 10000
    ctx.order_target_percent("000001", 0.1)
    ctx._broker.portfolio.equity.assert_called_once_with("2024-03-29")
    kwargs = ctx._broker.submit_order.call_args.kwargs
    assert kwargs["shares"] == 10000


# ===== 因子收集(策略雷达 / 选股回测) =====


def test_record_factor_writes_and_reads(ctx):
    ctx.record_factor("000001", "PE*PB", 18.5)
    ctx.record_factor("000001", "ROE", 12.3)
    ctx.record_factor("600519", "PE*PB", 32.1)
    assert ctx.get_factors("000001") == {"PE*PB": 18.5, "ROE": 12.3}
    assert ctx.get_factors("600519") == {"PE*PB": 32.1}
    assert ctx.get_factors("999999") == {}


def test_record_factor_overwrites_same_key(ctx):
    ctx.record_factor("000001", "PE", 10)
    ctx.record_factor("000001", "PE", 11)
    assert ctx.get_factors("000001") == {"PE": 11}


def test_get_factors_returns_copy(ctx):
    ctx.record_factor("000001", "PE", 10)
    snapshot = ctx.get_factors("000001")
    snapshot["PE"] = 999
    assert ctx.get_factors("000001") == {"PE": 10}


def test_reset_factors_clears(ctx):
    ctx.record_factor("000001", "PE", 10)
    ctx.record_factor("600519", "ROE", 20)
    ctx.reset_factors()
    assert ctx.get_factors("000001") == {}
    assert ctx.get_all_factors() == {}


def test_get_all_factors_returns_internal_dict(ctx):
    ctx.record_factor("A", "PE", 1)
    ctx.record_factor("B", "PB", 2)
    all_f = ctx.get_all_factors()
    assert all_f == {"A": {"PE": 1}, "B": {"PB": 2}}
