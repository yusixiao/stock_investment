"""MaTangleValueStrategy 元信息测试(Phase 2.3)。"""

import pytest
from strategies.examples.ma_tangle_value_strategy import MaTangleValueStrategy


def test_class_metadata():
    assert MaTangleValueStrategy.name == "月线均线缠绕价值策略"
    assert MaTangleValueStrategy.frequency == "monthly"
    assert MaTangleValueStrategy.frequency_overridable is False


def test_default_params_via_p_accessor():
    s = MaTangleValueStrategy()
    assert s.p.min_dividend_years == 5
    assert s.p.pe_pb_min == 0.0
    assert s.p.pe_pb_max == 22.0
    assert s.p.min_roe == 10.0
    assert s.p.ma_fast == 5
    assert s.p.ma_mid == 10
    assert s.p.ma_slow == 20
    assert s.p.tangle_threshold == 0.05
    assert s.p.tangle_months == 2
    assert s.p.spread_months == 6
    assert s.p.spread_threshold == 0.01
    assert s.p.vol_red_bars == 4
    assert s.p.buy_weeks == 8


def test_param_overrides():
    s = MaTangleValueStrategy(
        param_overrides={
            "min_dividend_years": 10,
            "pe_pb_max": 15.0,
            "buy_weeks": 4,
        }
    )
    assert s.p.min_dividend_years == 10
    assert s.p.pe_pb_max == 15.0
    assert s.p.buy_weeks == 4


def test_buyer_initialized_with_buy_weeks():
    s = MaTangleValueStrategy(param_overrides={"buy_weeks": 12})
    assert s._buyer._buy_weeks == 12


def test_default_settings_inherits_strategy_defaults():
    s = MaTangleValueStrategy()
    assert s.settings["initial_capital"] == 1_000_000
    assert s.settings["commission_rate"] == 0.0003
    assert s.settings["slippage"] == 0.002


def test_inherits_from_new_strategy_base():
    from services.backtest.base import Strategy

    assert issubclass(MaTangleValueStrategy, Strategy)
