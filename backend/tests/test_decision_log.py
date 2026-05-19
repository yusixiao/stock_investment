"""DecisionLogSink 单测(Phase 2.1)。"""

import json

import pytest

from services.backtest.decision_log import DecisionLogSink


@pytest.fixture
def sink(tmp_path):
    return DecisionLogSink(tmp_path, enabled=True)


def test_disabled_sink_is_noop(tmp_path):
    s = DecisionLogSink(tmp_path, enabled=False)
    s.log_pass("000001", "test.stage", idx=0, ts="2024-01-01", freq="daily", value=1)
    s.flush()
    assert not (tmp_path / "decisions.jsonl").exists()


def test_none_log_dir_is_noop():
    s = DecisionLogSink(None, enabled=True)
    s.log_pass("000001", "test.stage", idx=0, ts="2024-01-01", freq="daily")
    s.flush()


def test_log_pass_writes_jsonl_after_flush(sink, tmp_path):
    sink.log_pass(
        "000001", "dividend.years", idx=12, ts="2024-03-29", freq="monthly", years=8
    )
    sink.flush()
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["decision"] == "pass"
    assert rec["symbol"] == "000001"
    assert rec["stage"] == "dividend.years"
    assert rec["idx"] == 12
    assert rec["ts"] == "2024-03-29"
    assert rec["freq"] == "monthly"
    assert rec["years"] == 8


def test_log_reject_includes_reason(sink, tmp_path):
    sink.log_reject(
        "600519",
        "valuation.pe_pb_product",
        reason="above_max",
        idx=5,
        ts="2024-01-05",
        freq="monthly",
        product=68.5,
        max=22.0,
    )
    sink.flush()
    rec = json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["decision"] == "reject"
    assert rec["reason"] == "above_max"
    assert rec["product"] == 68.5


def test_log_flow_writes_to_flow_jsonl(sink, tmp_path):
    sink.log_flow(
        "strategy.screen.start", idx=0, ts="2024-01-01", input=4823, passed=421
    )
    sink.flush()
    rec = json.loads((tmp_path / "flow.jsonl").read_text().strip())
    assert rec["stage"] == "strategy.screen.start"
    assert rec["counts"] == {"input": 4823, "passed": 421}


def test_log_exec_writes_to_exec_jsonl(sink, tmp_path):
    sink.log_exec(
        "BUY",
        "601318",
        idx=200,
        ts="2024-04-01",
        shares=1300,
        price=35.20,
        note="week 1/8",
    )
    sink.flush()
    rec = json.loads((tmp_path / "exec.jsonl").read_text().strip())
    assert rec["action"] == "BUY"
    assert rec["symbol"] == "601318"
    assert rec["shares"] == 1300
    assert rec["price"] == 35.20
    assert rec["note"] == "week 1/8"


def test_buffer_does_not_write_until_flush(sink, tmp_path):
    sink.log_pass("000001", "x", idx=0, ts="2024-01-01", freq="daily")
    assert not (tmp_path / "decisions.jsonl").exists()
    sink.flush()
    assert (tmp_path / "decisions.jsonl").exists()


def test_multiple_records_appended_in_order(sink, tmp_path):
    for i in range(5):
        sink.log_pass(f"00000{i}", "test", idx=i, ts="2024-01-01", freq="daily")
    sink.flush()
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 5
    for i, line in enumerate(lines):
        assert json.loads(line)["idx"] == i
