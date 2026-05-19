"""验证 MockContext 现在能抓取 log_*(Phase 2.2)。"""

from backend.tests.utils_test_helpers import MockContext


def test_log_pass_recorded():
    ctx = MockContext()
    ctx.log_pass("000001", "stage.x", value=42)
    assert ctx.log_records["pass"] == [
        {"symbol": "000001", "stage": "stage.x", "value": 42}
    ]


def test_log_reject_recorded():
    ctx = MockContext()
    ctx.log_reject("000001", "stage.y", reason="too_low", actual=3, threshold=5)
    assert ctx.log_records["reject"][0]["reason"] == "too_low"
    assert ctx.log_records["reject"][0]["symbol"] == "000001"
    assert ctx.log_records["reject"][0]["stage"] == "stage.y"


def test_log_flow_recorded():
    ctx = MockContext()
    ctx.log_flow("pipeline.start", input=100, passed=42)
    assert ctx.log_records["flow"] == [
        {"stage": "pipeline.start", "input": 100, "passed": 42}
    ]


def test_passed_symbols_helper():
    ctx = MockContext()
    ctx.log_pass("A", "s")
    ctx.log_pass("B", "s")
    ctx.log_reject("C", "s", reason="x")
    assert ctx.passed_symbols("s") == ["A", "B"]
    assert ctx.rejected_symbols("s") == ["C"]
