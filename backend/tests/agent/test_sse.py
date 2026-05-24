"""问股期 1 / Task 4:SSE 6 类事件工厂测试。"""

import json

from services.agent.core import sse


def test_thinking_shape():
    e = sse.thinking("识别股票")
    assert e == {"type": "thinking", "content": "识别股票"}


def test_tool_start_shape():
    e = sse.tool_start("phase1", "采集市场数据")
    assert e == {
        "type": "tool_start",
        "tool": "phase1",
        "display_name": "采集市场数据",
    }


def test_tool_done_minimal():
    e = sse.tool_done("phase1", success=True)
    assert e == {"type": "tool_done", "tool": "phase1", "success": True}


def test_tool_done_full():
    e = sse.tool_done(
        "phase1", success=True, duration=1.8, message="ok", display_name="数据包"
    )
    assert e["duration"] == 1.8
    assert e["message"] == "ok"
    assert e["display_name"] == "数据包"
    assert e["success"] is True


def test_tool_done_failure():
    e = sse.tool_done("phase1", success=False, message="LLM 超时")
    assert e["success"] is False
    assert e["message"] == "LLM 超时"


def test_generating_shape():
    e = sse.generating("Step 0...")
    assert e == {"type": "generating", "content": "Step 0..."}


def test_done_shape():
    arts = [{"name": "report.md", "url": "/x"}]
    e = sse.done("# 报告", arts)
    assert e == {
        "type": "done",
        "success": True,
        "content": "# 报告",
        "artifacts": arts,
    }


def test_error_shape():
    e = sse.error("LLM_TIMEOUT", "超时", phase="phase3.1")
    assert e == {
        "type": "error",
        "error": "LLM_TIMEOUT",
        "message": "超时",
        "phase": "phase3.1",
    }


def test_error_without_phase():
    e = sse.error("BAD_INPUT", "无效输入")
    assert e == {"type": "error", "error": "BAD_INPUT", "message": "无效输入"}
    assert "phase" not in e


def test_encode_frame_format():
    raw = sse.encode({"type": "thinking", "content": "x"})
    assert raw.endswith(b"\n\n")
    assert raw.startswith(b"data: ")
    body = raw[len(b"data: ") : -2]
    assert json.loads(body) == {"type": "thinking", "content": "x"}


def test_encode_unicode_safe():
    """中文不应被 ASCII 转义。"""
    raw = sse.encode({"type": "thinking", "content": "识别股票"})
    assert "识别股票".encode("utf-8") in raw
