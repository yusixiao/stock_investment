from tests.utils_test_helpers import MockContext
from strategies.utils import valuation


def test_get_pe_returns_value():
    ctx = MockContext(valuation={"A": {"pe_ttm": 5.2, "pb": 0.7, "total_mv": 4.5e11}})
    assert valuation.get_pe(ctx, "A") == 5.2


def test_get_pb_returns_value():
    ctx = MockContext(valuation={"A": {"pe_ttm": 5.2, "pb": 0.7}})
    assert valuation.get_pb(ctx, "A") == 0.7


def test_get_total_mv_returns_value():
    ctx = MockContext(valuation={"A": {"total_mv": 4.5e11}})
    assert valuation.get_total_mv(ctx, "A") == 4.5e11


def test_get_pe_no_data_returns_none():
    ctx = MockContext()
    assert valuation.get_pe(ctx, "A") is None


def test_filter_by_pe_pb_product_in_range():
    ctx = MockContext(
        valuation={
            "P": {"pe_ttm": 4.0, "pb": 1.5},
            "F": {"pe_ttm": 30.0, "pb": 5.0},
        }
    )
    result = valuation.filter_by_pe_pb_product(
        ctx, ["P", "F"], min_value=0.0, max_value=22.0
    )
    assert result == ["P"]
    assert ctx.pass_logs == [
        (
            "P",
            "valuation.pe_pb_product",
            {"pe": 4.0, "pb": 1.5, "product": 6.0, "min": 0.0, "max": 22.0},
        )
    ]
    assert ctx.reject_logs == [
        (
            "F",
            "valuation.pe_pb_product",
            "above_max",
            {"pe": 30.0, "pb": 5.0, "product": 150.0, "min": 0.0, "max": 22.0},
        )
    ]


def test_filter_by_pe_pb_product_below_min():
    ctx = MockContext(valuation={"X": {"pe_ttm": 1.0, "pb": 0.5}})
    result = valuation.filter_by_pe_pb_product(
        ctx, ["X"], min_value=1.0, max_value=22.0
    )
    assert result == []
    assert ctx.reject_logs[0][2] == "below_min"


def test_filter_by_pe_pb_product_no_data():
    ctx = MockContext()
    result = valuation.filter_by_pe_pb_product(
        ctx, ["X"], min_value=0.0, max_value=22.0
    )
    assert result == []
    assert ctx.reject_logs == [
        ("X", "valuation.pe_pb_product", "no_data", {"min": 0.0, "max": 22.0})
    ]


def test_filter_by_pe_pb_product_missing_pe_or_pb():
    ctx = MockContext(valuation={"X": {"pe_ttm": 5.0}})
    result = valuation.filter_by_pe_pb_product(
        ctx, ["X"], min_value=0.0, max_value=22.0
    )
    assert result == []
    assert ctx.reject_logs[0][2] == "no_data"


def test_filter_by_pe_pb_product_logs_flow():
    ctx = MockContext(valuation={"P": {"pe_ttm": 4.0, "pb": 1.5}})
    valuation.filter_by_pe_pb_product(ctx, ["P", "X"], min_value=0.0, max_value=22.0)
    assert ctx.flow_logs == [("valuation.pe_pb_product", {"input": 2, "passed": 1})]
