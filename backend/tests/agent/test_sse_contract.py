"""问股期 1 / Task 5:SSE 契约 guard test。

每个 SSE 事件 dict 的 keys 必须严格属于前端 ProgressStep 允许集合。
前端 ProgressStep 字段(frontend/src/stores/agentChatStore.ts ~265-283):
  type, step?, tool?, display_name?, success?, duration?, message?, content?,
  error?, phase?, artifacts?
"""

from services.agent.core import sse

ALLOWED = {
    "type",
    "step",
    "tool",
    "display_name",
    "success",
    "duration",
    "message",
    "content",
    "error",
    "phase",
    "artifacts",
}


def test_all_factories_only_use_allowed_fields():
    events = [
        sse.thinking("x"),
        sse.tool_start("p1", "数据"),
        sse.tool_done(
            "p1", success=True, duration=1.0, message="ok", display_name="数据"
        ),
        sse.generating("y"),
        sse.done("# r", [{"name": "r.md", "url": "/x"}]),
        sse.error("E1", "msg", phase="p1"),
        sse.error("E2", "msg2"),  # 无 phase
    ]
    for ev in events:
        unknown = set(ev.keys()) - ALLOWED
        assert not unknown, f"event {ev['type']} has unknown keys {unknown}"


def test_type_values_in_allowed_set():
    types = {
        sse.thinking("")["type"],
        sse.tool_start("", "")["type"],
        sse.tool_done("", success=True)["type"],
        sse.generating("")["type"],
        sse.done("", [])["type"],
        sse.error("", "")["type"],
    }
    assert types == {
        "thinking",
        "tool_start",
        "tool_done",
        "generating",
        "done",
        "error",
    }
