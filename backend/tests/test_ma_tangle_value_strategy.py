"""MaTangleValueStrategy 元信息 + screen() 集成测试(Phase 2.3 / 2.4)。"""

import pytest
from strategies.deployed import ma_tangle_value_strategy as strategy_module
from strategies.deployed.ma_tangle_value_strategy import MaTangleValueStrategy
from backend.tests.utils_test_helpers import MockContext, make_tangle_breakout_stub


def test_class_metadata():
    assert MaTangleValueStrategy.name == "月线均线缠绕价值策略"
    assert MaTangleValueStrategy.frequency == "monthly"
    assert MaTangleValueStrategy.frequency_overridable is False


def test_default_params_via_p_accessor():
    s = MaTangleValueStrategy()
    assert s.p.min_dividend_years == 5
    assert s.p.pe_min == 0.0
    assert s.p.pe_max == 22.0
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
            "pe_max": 15.0,
            "buy_weeks": 4,
        }
    )
    assert s.p.min_dividend_years == 10
    assert s.p.pe_max == 15.0
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
    from strategies.base import Strategy

    assert issubclass(MaTangleValueStrategy, Strategy)


# ===== Phase 2.4:screen() 集成测(MockContext + monkeypatch tangle 检测)=====


def _build_full_mock_context() -> MockContext:
    """构造覆盖三层过滤分支的 8 只股票场景:
    A: 分红 8 / PE=10 / ROE=12 / 月线缠绕命中     → 通过到 final
    B: 分红 3                                    → dividend 淘汰
    C: 分红 8 / PE=40(>22)                       → valuation 淘汰
    D: 分红 8 / PE=10 / ROE=8                     → financial 淘汰
    E: 分红 8 / PE=10 / ROE=12 / 月线无缠绕       → kline 淘汰
    F-H: 同 A,通过到 final
    """
    ctx = MockContext()
    ctx.set_dividend_years(
        {"A": 8, "B": 3, "C": 8, "D": 8, "E": 8, "F": 8, "G": 8, "H": 8}
    )
    ctx.set_pe_pb(
        {
            "A": (10, 1.5),
            "C": (40, 1.7),
            "D": (10, 1.5),
            "E": (10, 1.5),
            "F": (10, 1.5),
            "G": (10, 1.5),
            "H": (10, 1.5),
        }
    )
    ctx.set_roe({"A": 12, "D": 8, "E": 12, "F": 12, "G": 12, "H": 12})
    ctx.set_ma_tangle_breakout_hits({"A", "F", "G", "H"})
    return ctx


@pytest.fixture
def full_ctx(monkeypatch) -> MockContext:
    ctx = _build_full_mock_context()
    # 替换 utils.kline.detect_ma_tangle_breakout(策略通过 `kline.detect_...` 调用)
    monkeypatch.setattr(
        strategy_module.kline,
        "detect_ma_tangle_breakout",
        make_tangle_breakout_stub(ctx),
    )
    return ctx


def test_screen_returns_only_full_pass_symbols(full_ctx):
    s = MaTangleValueStrategy()
    signals = s.screen(full_ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    assert set(signals) == {"A", "F", "G", "H"}


def test_screen_logs_each_filter_stage_flow(full_ctx):
    s = MaTangleValueStrategy()
    s.screen(full_ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    flow_stages = [r["stage"] for r in full_ctx.log_records["flow"]]
    assert "strategy.screen.start" in flow_stages
    assert "strategy.fundamental_pool" in flow_stages
    assert "strategy.screen.done" in flow_stages


def test_screen_logs_pass_for_each_final_signal(full_ctx):
    s = MaTangleValueStrategy()
    s.screen(full_ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    final_passed = full_ctx.passed_symbols("strategy.screen.final")
    assert set(final_passed) == {"A", "F", "G", "H"}


def test_screen_short_circuits_on_dividend_filter(full_ctx):
    """B 在 dividend 阶段被拒,后续 valuation/financial 阶段不应再出现。"""
    s = MaTangleValueStrategy()
    s.screen(full_ctx, ["A", "B", "C", "D", "E", "F", "G", "H"])
    rejected_in_valuation = full_ctx.rejected_symbols("valuation.pe")
    rejected_in_financial = full_ctx.rejected_symbols("financial.roe")
    assert "B" not in rejected_in_valuation
    assert "B" not in rejected_in_financial


def test_screen_param_override_changes_output(monkeypatch):
    ctx = _build_full_mock_context()
    monkeypatch.setattr(
        strategy_module.kline,
        "detect_ma_tangle_breakout",
        make_tangle_breakout_stub(ctx),
    )
    # 收紧 PE 上限到 8,A 的 PE=10 应被淘汰
    s = MaTangleValueStrategy(param_overrides={"pe_max": 8.0})
    signals = s.screen(ctx, ["A", "F", "G", "H"])
    assert "A" not in signals
