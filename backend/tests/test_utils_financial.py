from tests.utils_test_helpers import MockContext
from strategies.utils import financial


def test_get_roe_returns_value():
    ctx = MockContext(financial={"A": {"ROEJQ": 14.7}})
    assert financial.get_roe(ctx, "A") == 14.7


def test_get_roe_returns_none_when_missing_data():
    ctx = MockContext()
    assert financial.get_roe(ctx, "A") is None


def test_get_roe_returns_none_when_field_missing():
    ctx = MockContext(financial={"A": {"EPSJB": 1.2}})
    assert financial.get_roe(ctx, "A") is None


def test_get_eps_basic():
    ctx = MockContext(financial={"A": {"EPSJB": 1.2}})
    assert financial.get_eps(ctx, "A") == 1.2


def test_get_net_profit_growth_basic():
    ctx = MockContext(financial={"A": {"PARENTNETPROFITTZ": 25.4}})
    assert financial.get_net_profit_growth(ctx, "A") == 25.4


def test_filter_by_roe_pass_and_reject():
    ctx = MockContext(
        financial={
            "P": {"ROEJQ": 14.7},
            "F": {"ROEJQ": 8.4},
        }
    )
    result = financial.filter_by_roe(ctx, ["P", "F"], min_roe=10.0)
    assert result == ["P"]
    assert ctx.pass_logs == [("P", "financial.roe", {"roe": 14.7, "threshold": 10.0})]
    assert ctx.reject_logs == [
        ("F", "financial.roe", "below_threshold", {"roe": 8.4, "threshold": 10.0})
    ]


def test_filter_by_roe_no_data():
    ctx = MockContext()
    result = financial.filter_by_roe(ctx, ["X"], min_roe=10.0)
    assert result == []
    assert ctx.reject_logs == [("X", "financial.roe", "no_data", {"threshold": 10.0})]


def test_filter_by_roe_field_missing():
    ctx = MockContext(financial={"X": {"EPSJB": 1.2}})
    result = financial.filter_by_roe(ctx, ["X"], min_roe=10.0)
    assert result == []
    assert ctx.reject_logs == [("X", "financial.roe", "no_data", {"threshold": 10.0})]


def test_filter_by_roe_logs_flow_summary():
    ctx = MockContext(financial={"P": {"ROEJQ": 14.7}})
    financial.filter_by_roe(ctx, ["P", "X"], min_roe=10.0)
    assert ctx.flow_logs == [("financial.roe", {"input": 2, "passed": 1})]
